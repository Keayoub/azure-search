import datetime
import os
import azure.functions as func
import logging
from function_prepdocs import PrepDocsManager


app = func.FunctionApp()


@app.schedule(schedule="0 */30 * * * *", arg_name="myTimer", 
            run_on_startup=False, use_monitor=False)
def prepare_docs(myTimer: func.TimerRequest) -> None:
    if myTimer.past_due:
        logging.info("The timer is past due!")

    fc = PrepDocsManager()

    use_local_pdf_parser = os.getenv("USE_LOCAL_PDF_PARSER", "false").lower() == "true"

    # List blobs in the container
    blob_list = fc.blob_service.get_container_client(fc.container_name).list_blobs()
    if not blob_list:
        logging.info(f"No blobs found in container '{fc.container_name}'")
        return

    logging.info(f"Start Processing files in container {fc.container_name}...")

    # for key in os.environ.keys():
    #     logging.info(f"{key} = {os.environ[key]}")

    # First run create search index
    fc.create_search_index(os.getenv("AZURE_SEARCH_INDEX", "local-index"))

    for blob in blob_list:
        # Send blob to Form Recognizer for data extraction
        page_map = fc.get_document_text(blob.name, use_local_pdf_parser)
        # Split PDF into sections
        sections = fc.create_sections(blob.name, page_map, True)
        # Upload sections to blob container
        fc.index_sections(os.path.basename(blob.name), sections)

        logging.info(f"Finished Processing files in container {fc.container_name}...")



@app.route(route="delete_all", auth_level=func.AuthLevel.FUNCTION)
def delete_all(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Python HTTP trigger function processed a request.")

    fc = PrepDocsManager()
    fc.remove_blobs(None)

    return func.HttpResponse("This HTTP triggered function executed successfully. All blobs removed.", status_code=200)


@app.blob_trigger(arg_name="myblob", path="uploads", connection="AzureWebJobsStorage")
def BlobTrigger(myblob: func.InputStream):
    fc = PrepDocsManager()
    # Split PDF into pages
    if os.path.splitext(myblob.name)[1].lower() == ".pdf":
        fullpdfcontent = myblob.read()
        fc.split_upload_blobs(myblob.name, fullpdfcontent)

    # run index on all blobs in container
    use_local_pdf_parser = os.getenv("USE_LOCAL_PDF_PARSER", "false").lower() == "true"

    # List blobs in the container
    blob_list = fc.blob_service.get_container_client(fc.container_name).list_blobs()
    if not blob_list:
        logging.info(f"No blobs found in container '{fc.container_name}'")
        return

    logging.info(f"Start Processing files in container {fc.container_name}...")

    # for key in os.environ.keys():
    #     logging.info(f"{key} = {os.environ[key]}")

    # First run create search index
    fc.create_search_index()

    for blob in blob_list:
        # Send blob to Form Recognizer for data extraction
        page_map = fc.get_document_text(blob.name, use_local_pdf_parser)
        # Split PDF into sections
        sections = fc.create_sections(blob.name, page_map, True)
        # Upload sections to blob container
        fc.index_sections(os.path.basename(blob.name), sections)

        logging.info(f"Finished Processing files in container {fc.container_name}...")

    else:
        # copy myblob to new container using python
        fc.blob_service.get_blob_client(fc.container_name, myblob.name).start_copy_from_url(myblob.uri)


    logging.info(f"Python blob trigger function processed blob" f"Name: {myblob.name}," f"Blob Size: {myblob.length} bytes")
    return
