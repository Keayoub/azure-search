import logging
import os
import base64
import html
import re
import time
import openai

from azure.identity import DefaultAzureCredential
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import PrioritizedFields, SearchableField, SearchField, SearchFieldDataType, SearchIndex, SemanticConfiguration, SemanticField, SemanticSettings, SimpleField, VectorSearch, VectorSearchAlgorithmConfiguration, HnswParameters

from pypdf import PdfReader
from tenacity import retry, stop_after_attempt, wait_random_exponential
import function_blobs as fb

MAX_SECTION_LENGTH = 5000
SENTENCE_SEARCH_LIMIT = 100
SECTION_OVERLAP = 100

# use azure identity to get credentials
credential = DefaultAzureCredential()

# Utilities functions


def split_text(filename, page_map):
    SENTENCE_ENDINGS = [".", "!", "?"]
    WORDS_BREAKS = [",", ";", ":", " ", "(", ")", "[", "]", "{", "}", "\t", "\n"]
    logging.info(f"Splitting '{filename}' into sections")

    def find_page(offset):
        num_pages = len(page_map)
        for i in range(num_pages - 1):
            if offset >= page_map[i][1] and offset < page_map[i + 1][1]:
                return i
        return num_pages - 1

    all_text = "".join(p[2] for p in page_map)
    length = len(all_text)
    start = 0
    end = length
    while start + SECTION_OVERLAP < length:
        last_word = -1
        end = start + MAX_SECTION_LENGTH

        if end > length:
            end = length
        else:
            # Try to find the end of the sentence
            while end < length and (end - start - MAX_SECTION_LENGTH) < SENTENCE_SEARCH_LIMIT and all_text[end] not in SENTENCE_ENDINGS:
                if all_text[end] in WORDS_BREAKS:
                    last_word = end
                end += 1
            if end < length and all_text[end] not in SENTENCE_ENDINGS and last_word > 0:
                end = last_word  # Fall back to at least keeping a whole word
        if end < length:
            end += 1

        # Try to find the start of the sentence or at least a whole word boundary
        last_word = -1
        while start > 0 and start > end - MAX_SECTION_LENGTH - 2 * SENTENCE_SEARCH_LIMIT and all_text[start] not in SENTENCE_ENDINGS:
            if all_text[start] in WORDS_BREAKS:
                last_word = start
            start -= 1
        if all_text[start] not in SENTENCE_ENDINGS and last_word > 0:
            start = last_word
        if start > 0:
            start += 1

        section_text = all_text[start:end]
        yield (section_text, find_page(start))

        last_table_start = section_text.rfind("<table")
        if last_table_start > 2 * SENTENCE_SEARCH_LIMIT and last_table_start > section_text.rfind("</table"):
            # If the section ends with an unclosed table, we need to start the next section with the table.
            # If table starts inside SENTENCE_SEARCH_LIMIT, we ignore it, as that will cause an infinite loop for tables longer than MAX_SECTION_LENGTH
            # If last table starts inside SECTION_OVERLAP, keep overlapping
            logging.info(f"Section ends with unclosed table, starting next section with the table at page {find_page(start)} offset {start} table start {last_table_start}")
            start = min(end - SECTION_OVERLAP, start + last_table_start)
        else:
            start = end - SECTION_OVERLAP

    if start + SECTION_OVERLAP < end:
        yield (all_text[start:end], find_page(start))


def table_to_html(table):
    table_html = "<table>"
    rows = [sorted([cell for cell in table.cells if cell.row_index == i], key=lambda cell: cell.column_index) for i in range(table.row_count)]
    for row_cells in rows:
        table_html += "<tr>"
        for cell in row_cells:
            tag = "th" if (cell.kind == "columnHeader" or cell.kind == "rowHeader") else "td"
            cell_spans = ""
            if cell.column_span > 1:
                cell_spans += f" colSpan={cell.column_span}"
            if cell.row_span > 1:
                cell_spans += f" rowSpan={cell.row_span}"
            table_html += f"<{tag}{cell_spans}>{html.escape(cell.content)}</{tag}>"
        table_html += "</tr>"
    table_html += "</table>"
    return table_html


def get_document_text(filename, localpdfparser):
    offset = 0
    page_map = []
    if localpdfparser:
        reader = PdfReader(filename)
        pages = reader.pages
        for page_num, p in enumerate(pages):
            page_text = p.extract_text()
            page_map.append((page_num, offset, page_text))
            offset += len(page_text)
    else:
        # Set up Form Recognizer Client
        form_recognizer_service = os.getenv("AZURE_FORMRECOGNIZER_SERVICE")
        endpoint = f"https://{form_recognizer_service}.cognitiveservices.azure.com/"
        form_recognizer_client = DocumentAnalysisClient(endpoint, credential, headers={"x-ms-useragent": "azure-search-chat-demo/1.0.0"})

        with open(filename, "rb") as f:
            poller = form_recognizer_client.begin_analyze_document("prebuilt-layout", document=f)
        form_recognizer_results = poller.result()

        for page_num, page in enumerate(form_recognizer_results.pages):
            tables_on_page = [table for table in form_recognizer_results.tables if table.bounding_regions[0].page_number == page_num + 1]

            # mark all positions of the table spans in the page
            page_offset = page.spans[0].offset
            page_length = page.spans[0].length
            table_chars = [-1] * page_length
            for table_id, table in enumerate(tables_on_page):
                for span in table.spans:
                    # replace all table spans with "table_id" in table_chars array
                    for i in range(span.length):
                        idx = span.offset - page_offset + i
                        if idx >= 0 and idx < page_length:
                            table_chars[idx] = table_id

            # build page text by replacing charcters in table spans with table html
            page_text = ""
            added_tables = set()
            for idx, table_id in enumerate(table_chars):
                if table_id == -1:
                    page_text += form_recognizer_results.content[page_offset + idx]
                elif table_id not in added_tables:
                    page_text += table_to_html(tables_on_page[table_id])
                    added_tables.add(table_id)

            page_text += " "
            page_map.append((page_num, offset, page_text))
            offset += len(page_text)

    return page_map


def filename_to_id(filename):
    filename_ascii = re.sub("[^0-9a-zA-Z_-]", "_", filename)
    filename_hash = base64.b16encode(filename.encode("utf-8")).decode("ascii")
    return f"file-{filename_ascii}-{filename_hash}"


def create_sections(filename, page_map, use_vectors):
    file_id = filename_to_id(filename)
    for i, (content, page_num) in enumerate(split_text(filename, page_map)):
        section = {"id": f"{file_id}-page-{i}", "content": content, "category": "", "sourcepage": fb.blob_name_from_file_page(filename, page_num), "sourcefile": filename}
        if use_vectors:
            section["embedding"] = compute_embedding(content)
        yield section


def compute_embedding(text):
    # Get Azure OpenAI credentials
    openai.api_type = "azure_ad"
    openai.api_key = credential.get_token("https://cognitiveservices.azure.com/.default").token
    openai.api_version = "2022-12-01"

    openai_service = os.getenv("AZURE_OPENAI_SERVICE")
    openai.api_base = f"https://{openai_service}.openai.azure.com"

    openaideployment = os.getenv("AZURE_OPENAI_EMB_DEPLOYMENT")
    return openai.Embedding.create(engine=openaideployment, input=text)["data"][0]["embedding"]


def create_search_index(index_name):
    search_service = os.getenv("AZURE_SEARCH_SERVICE")
    search_creds = credential
    index_client = SearchIndexClient(endpoint=f"https://{search_service}.search.windows.net/", credential=search_creds)
    if index_name not in index_client.list_index_names():
        index = SearchIndex(
            name=index_name,
            fields=[
                SimpleField(name="id", type="Edm.String", key=True),
                SearchableField(name="content", type="Edm.String", analyzer_name="en.microsoft"),
                SearchField(name="embedding", type=SearchFieldDataType.Collection(SearchFieldDataType.Single), hidden=False, searchable=True, filterable=False, sortable=False, facetable=False, vector_search_dimensions=1536, vector_search_configuration="default"),
                SimpleField(name="category", type="Edm.String", filterable=True, facetable=True),
                SimpleField(name="sourcepage", type="Edm.String", filterable=True, facetable=True),
                SimpleField(name="sourcefile", type="Edm.String", filterable=True, facetable=True),
            ],
            semantic_settings=SemanticSettings(configurations=[SemanticConfiguration(name="default", prioritized_fields=PrioritizedFields(title_field=None, prioritized_content_fields=[SemanticField(field_name="content")]))]),
            vector_search=VectorSearch(algorithm_configurations=[VectorSearchAlgorithmConfiguration(name="default", kind="hnsw", hnsw_parameters=HnswParameters(metric="cosine"))]),
        )
        logging.info(f"Creating {index_name} search index")
        index_client.create_index(index)
    else:
        logging.info(f"Search index {index_name} already exists")


def index_sections(filename, sections, index_name):
    search_service = os.getenv("AZURE_SEARCH_SERVICE")
    search_creds = credential
    search_client = SearchClient(endpoint=f"https://{search_service}.search.windows.net/", index_name=index_name, credential=search_creds)
    i = 0
    batch = []
    for s in sections:
        batch.append(s)
        i += 1
        if i % 1000 == 0:
            results = search_client.upload_documents(documents=batch)
            succeeded = sum([1 for r in results if r.succeeded])
            logging.info(f"\tIndexed {len(results)} sections, {succeeded} succeeded")
            batch = []

    if len(batch) > 0:
        results = search_client.upload_documents(documents=batch)
        succeeded = sum([1 for r in results if r.succeeded])
        logging.info(f"\tIndexed {len(results)} sections, {succeeded} succeeded")


def remove_from_index(filename, index):
    logging.info(f"Removing sections from '{filename or '<all>'}' from search index '{index}'")
    search_service = os.getenv("AZURE_SEARCH_SERVICE")
    search_creds = credential
    search_client = SearchClient(endpoint=f"https://{search_service}.search.windows.net/", index_name=index, credential=search_creds)
    while True:
        filter = None if filename is None else f"sourcefile eq '{os.path.basename(filename)}'"
        r = search_client.search("", filter=filter, top=1000, include_total_count=True)
        if r.get_count() == 0:
            break
        r = search_client.delete_documents(documents=[{"id": d["id"]} for d in r])
        logging.info(f"\tRemoved {len(r)} sections from index")
        # It can take a few seconds for search results to reflect changes, so wait a bit
        time.sleep(2)