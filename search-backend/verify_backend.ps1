$baseUri = "http://localhost:8000"

# 1. Ingest Bookmark
Write-Host "Ingesting bookmark..." -ForegroundColor Cyan
$ingestPayload = @{
    url              = "https://spring.io/guides/gs/rest-service/"
    title            = "Building a RESTful Web Service"
    content_markdown = "This guide walks you through the process of creating a Hello World RESTful web service with Spring Boot. You will build a service that will accept HTTP GET requests at http://localhost:8080/greeting."
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri "$baseUri/bookmarks" -Method Post -Body $ingestPayload -ContentType "application/json"
    Write-Host "Ingest Success: $($response.id)" -ForegroundColor Green
}
catch {
    Write-Host "Ingest Failed: $_" -ForegroundColor Red
    exit 1
}

# 2. Search
Write-Host "`nSearching for 'create rest api java'..." -ForegroundColor Cyan
$searchPayload = @{
    query = "create rest api java"
    limit = 3
} | ConvertTo-Json

try {
    $results = Invoke-RestMethod -Uri "$baseUri/search" -Method Post -Body $searchPayload -ContentType "application/json"
    
    if ($results.Count -gt 0) {
        Write-Host "Search Success! Found $($results.Count) results." -ForegroundColor Green
        foreach ($res in $results) {
            Write-Host " - Title: $($res.title)"
            Write-Host "   URL:   $($res.url)"
            Write-Host "   Text:  $($res.text.Substring(0, 50))..."
            Write-Host ""
        }
    }
    else {
        Write-Host "Search returned no results." -ForegroundColor Yellow
    }
}
catch {
    Write-Host "Search Failed: $_" -ForegroundColor Red
    exit 1
}
