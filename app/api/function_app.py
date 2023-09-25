import datetime
import os
import azure.functions as func
import logging

app = func.FunctionApp()

@app.schedule(schedule="0 * * * * *", arg_name="myTimer", run_on_startup=False,
              use_monitor=False) 
def prepare_docs(myTimer: func.TimerRequest) -> None:
    if myTimer.past_due:
        logging.info('The timer is past due!')

    from function_blobs import fb
    from function_prepdocs import fc
    
    utc_timestamp = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).isoformat()

    if myTimer.past_due:
        logging.info('The timer is past due!')
           
    use_local_pdf_parser = os.getenv("USE_LOCAL_PDF_PARSER", "false").lower() == "true"
           
    # List blobs in the container
    blob_list = fb.blob_service.get_container_client(fb.container_name).list_blobs()
    if not blob_list:
        logging.info(f"No blobs found in container '{fb.container_name}'")
        return
    
    logging.info(f'Start Processing files in container {fb.container_name}...')
    for blob in blob_list:        
        # Send blob to Form Recognizer for data extraction
        page_map = fc.get_document_text(blob.name, use_local_pdf_parser)         
        sections = fc.create_sections(os.path.basename(blob.name), page_map, True)
        fc.index_sections(os.path.basename(blob.name), sections)
      
    logging.info('Python timer trigger function ran at %s', utc_timestamp)

@app.route(route="delete_blob", auth_level=func.AuthLevel.FUNCTION)
def delete_blob(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    blobname = req.params.get('blobname')
    if not blobname:
        try:
            req_body = req.get_json()
        except ValueError:
            pass
        else:
            blobname = req_body.get('blobname')

    from function_blobs import fb    
    if blobname:
        fb.remove_blobs(blobname)
        return func.HttpResponse(f"Hello, {blobname}. This HTTP triggered function executed successfully.")
    else:
        return func.HttpResponse(
             "This HTTP triggered function executed successfully. Pass a blobname in the query string or in the request body for a personalized response",
             status_code=200
        )
    
@app.route(route="delete_all", auth_level=func.AuthLevel.FUNCTION)
def delete_all(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    from function_blobs import fb    
    fb.remove_blobs(None)
    
    return func.HttpResponse(
             "This HTTP triggered function executed successfully. All blobs removed.",
             status_code=200
        )


