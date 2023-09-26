import logging
import os
import io
import os
import re

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from pypdf import PdfReader, PdfWriter

class BlobManager:
    def __init__(self):
        self.credential = DefaultAzureCredential()
        self.storage_account = os.getenv("AZURE_STORAGE_ACCOUNT")
        self.container_name = os.getenv("AZURE_STORAGE_CONTAINER")
        self.blob_service = BlobServiceClient(account_url=f"https://{self.storage_account}.blob.core.windows.net", credential=self.credential)
        self.blob_container = self.blob_service.get_container_client(self.container_name)

    def blob_name_from_file_page(self, filename, page = 0):
        if os.path.splitext(filename)[1].lower() == ".pdf":
            return os.path.splitext(os.path.basename(filename))[0] + f"-{page}" + ".pdf"
        else:
            return os.path.basename(filename)

    def upload_blobs(self, filename):                 
        if not self.blob_container.exists():
            self.blob_container.create_container()

        # if file is PDF split into pages and upload each page as a separate blob
        if os.path.splitext(filename)[1].lower() == ".pdf":
            reader = PdfReader(filename)
            pages = reader.pages
            for i in range(len(pages)):
                blob_name = self.blob_name_from_file_page(filename, i)
                logging.info(f"\tUploading blob for page {i} -> {blob_name}")
                f = io.BytesIO()
                writer = PdfWriter()
                writer.add_page(pages[i])
                writer.write(f)
                f.seek(0)
                self.blob_container.upload_blob(blob_name, f, overwrite=True)
        else:
            blob_name = self.blob_name_from_file_page(filename)
            with open(filename,"rb") as data:
                self.blob_container.upload_blob(blob_name, data, overwrite=True)

    def remove_blobs(self, filename):
        logging.info(f"Removing blobs for '{filename or '<all>'}'")        
        if self.blob_container.exists():
            if filename is None:
                blobs = self.blob_container.list_blob_names()
            else:
                prefix = os.path.splitext(os.path.basename(filename))[0]
                blobs = filter(lambda b: re.match(f"{prefix}-\d+\.pdf", b), self.blob_container.list_blob_names(name_starts_with=os.path.splitext(os.path.basename(prefix))[0]))
            for b in blobs:
                logging.info(f"\tRemoving blob {b}")
                self.blob_container.delete_blob(b)
