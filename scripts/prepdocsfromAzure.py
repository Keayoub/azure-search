import os
import argparse
import glob

from azure.storage.blob import BlobServiceClient
from azure.identity import AzureDeveloperCliCredential
from azure.core.credentials import AzureKeyCredential

def download_blob(blob_service_client, container_name, blob_name, local_path):
    blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)
    blob_data = blob_client.download_blob()
    with open(local_path, "wb") as file:
        file.write(blob_data.readall())

def main(args):
    blob_service_client = BlobServiceClient(account_url=f"https://{args.storageaccount}.blob.core.windows.net", credential=storage_creds)
    container_name = args.container
    source_container_client = blob_service_client.get_container_client(container_name)

    if source_container_client.exists() is False:
        print(f"Container {container_name} does not exist")
        return
    
    for blob in source_container_client.list_blobs():
        local_path = os.path.join(args.local_folder, blob.name)
        if os.path.splitext(blob.name)[1].lower() == ".pdf":
            download_blob(blob_service_client, container_name, blob.name, local_path)
            print(f"Downloaded {blob.name} to {local_path}")
        else:
            print(f"Skipping {blob.name} as it is not a PDF file")

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Download blobs from Azure Blob Storage container" , 
                                     epilog="Example: prepdocsfromAzure.py --local_folder '..\data\*' --storageaccount myaccount --container mycontainer -v " )
    parser.add_argument("--local_folder", required=True, help="Path to the local folder where blobs will be downloaded")
    parser.add_argument("--container", required=True, help="Name of the Azure Blob Storage container")
    parser.add_argument("--storageaccount", required=True, help="Name of the Azure Blob Storage account")
    parser.add_argument("--storagekey", required=False, help="Optional. Use this Azure Blob Storage account key instead of the current user identity to login (use az login to set current user for Azure)")
    parser.add_argument("--tenantid", required=False, help="Optional. Use this to define the Azure directory where to authenticate)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    
    args = parser.parse_args()

    # Use the current user identity to connect to Azure services unless a key is explicitly set for any of them
    azd_credential = AzureDeveloperCliCredential() if args.tenantid is None else AzureDeveloperCliCredential(tenant_id=args.tenantid, process_timeout=60)
    default_creds = azd_credential if args.storagekey is None else None    
    storage_creds = default_creds if args.storagekey is None else args.storagekey

    #connection_string = f"DefaultEndpointsProtocol=https;AccountName={args.storage_account};AccountKey=YOUR_ACCOUNT_KEY;EndpointSuffix=core.windows.net"  # Replace with your storage account key
    main(args)
