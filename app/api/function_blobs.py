import logging
import os
import io
import os
import re

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from pypdf import PdfReader, PdfWriter

credential = DefaultAzureCredential()  
storage_account = os.getenv("AZURE_STORAGE_ACCOUNT")
container_name = os.getenv("AZURE_STORAGE_CONTAINER")
blob_service = BlobServiceClient(account_url=f"https://{storage_account}.blob.core.windows.net", credential=credential)
blob_container = blob_service.get_container_client(container_name)

def blob_name_from_file_page(filename, page = 0):
    if os.path.splitext(filename)[1].lower() == ".pdf":
        return os.path.splitext(os.path.basename(filename))[0] + f"-{page}" + ".pdf"
    else:
        return os.path.basename(filename)

def upload_blobs(filename):                 
    if not blob_container.exists():
        blob_container.create_container()

    # if file is PDF split into pages and upload each page as a separate blob
    if os.path.splitext(filename)[1].lower() == ".pdf":
        reader = PdfReader(filename)
        pages = reader.pages
        for i in range(len(pages)):
            blob_name = blob_name_from_file_page(filename, i)
            logging.info(f"\tUploading blob for page {i} -> {blob_name}")
            f = io.BytesIO()
            writer = PdfWriter()
            writer.add_page(pages[i])
            writer.write(f)
            f.seek(0)
            blob_container.upload_blob(blob_name, f, overwrite=True)
    else:
        blob_name = blob_name_from_file_page(filename)
        with open(filename,"rb") as data:
            blob_container.upload_blob(blob_name, data, overwrite=True)

def remove_blobs(filename):
    logging.info(f"Removing blobs for '{filename or '<all>'}'")        
    if blob_container.exists():
        if filename is None:
            blobs = blob_container.list_blob_names()
        else:
            prefix = os.path.splitext(os.path.basename(filename))[0]
            blobs = filter(lambda b: re.match(f"{prefix}-\d+\.pdf", b), blob_container.list_blob_names(name_starts_with=os.path.splitext(os.path.basename(prefix))[0]))
        for b in blobs:
            logging.info(f"\tRemoving blob {b}")
            blob_container.delete_blob(b)
