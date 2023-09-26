import os
import azure.functions as func
import logging
from function_prepdocs import PrepDocsManager

app = func.FunctionApp()

@app.function_name(name="prepare_docs")
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


@app.function_name(name="delete_all")
@app.route(route="delete_all", auth_level=func.AuthLevel.FUNCTION)
def delete_all(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Python HTTP trigger function processed a request.")

    fc = PrepDocsManager()
    fc.remove_blobs(None)

    return func.HttpResponse("This HTTP triggered function executed successfully. All blobs removed.", status_code=200)


@app.function_name(name="chunck_blob")
@app.blob_trigger(arg_name="myblob", path="uploads", connection="AzureWebJobsStorage")
def chunck_blob(myblob: func.InputStream) -> None:
    fc = PrepDocsManager()

    # Create container processed if not exists
    if not fc.blob_service.get_container_client("processed").exists():
            fc.blob_service.create_container("processed")

    # Get blob name without container name
    path_parts = myblob.name.split("/")
    source_container_name = path_parts[0]
    blob_name = path_parts[1]
    dest_container_name = "processed"

    if os.path.splitext(blob_name)[1].lower() == ".pdf":    
        fullpdfcontent = myblob.read()
        fc.split_upload_blobs(blob_name, fullpdfcontent)
        # run index on all blobs in container
        use_local_pdf_parser = os.getenv("USE_LOCAL_PDF_PARSER").lower() == "true"
        # List blobs in the container
        blob_list = fc.blob_service.get_container_client(fc.container_name).list_blobs(name_starts_with=os.path.splitext(blob_name)[0])
        if not blob_list:
            logging.info(f"No blobs found in container '{fc.container_name}'")
            return

        logging.info(f"Start Processing files in container {fc.container_name}...")    
        fc.create_search_index()        
        
        # for blob in blob_list:
        #     # Send blob to Form Recognizer for data extraction
        #     page_map = fc.get_document_text(blob.name, use_local_pdf_parser)
        #     # Split PDF into sections
        #     sections = fc.create_sections(blob.name, page_map, True)
        #     # Upload sections to blob container
        #     fc.index_sections(os.path.basename(blob.name), sections)
        
    # Get the source blob client
    source_blob_client = fc.blob_service.get_blob_client(container=source_container_name, blob=blob_name)
    
    # Get the destination blob client
    dest_blob_client = fc.blob_service.get_blob_client(container=dest_container_name, blob=blob_name)
    
    try:
        # Start copying the blob
        dest_blob_client.start_copy_from_url(source_blob_client.url)                    
        # Delete the source blob after copying
        source_blob_client.delete_blob()                
    except Exception as e:
        logging.error(f"Exception: {e}")        
                  
    
