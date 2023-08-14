$Header = @{
    "authorization" = "Basic <Personal-Access-Token>"
}

$Parameters = @{
    Method      = "POST"
    Uri         = "https://dev.azure.com/{organization}/{project}/_apis/build/builds?definitionId=1&api-version=6.0"
    Headers     = $Header
    ContentType = "application/json"
}
Invoke-RestMethod @Parameters