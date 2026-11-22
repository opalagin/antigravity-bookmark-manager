$url = "https://example.com/unique-upsert-test"

# 1. First Insert
$body1 = @{
    url              = $url
    title            = "Upsert Test v1"
    content_markdown = "This is the first version content."
} | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8000/bookmarks" -Method Post -Body $body1 -ContentType "application/json" | Out-Null
Write-Output "Inserted v1"

# 2. Second Insert (Update)
$body2 = @{
    url              = $url
    title            = "Upsert Test v2 (UPDATED)"
    content_markdown = "This is the updated content."
} | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8000/bookmarks" -Method Post -Body $body2 -ContentType "application/json" | Out-Null
Write-Output "Inserted v2 (Should be update)"

# 3. Verify
$response = Invoke-RestMethod -Uri "http://localhost:8000/recent?limit=5" -Method Get
$bookmark = $response | Where-Object { $_.url -eq $url }

if ($bookmark) {
    Write-Output "Found Bookmark: $($bookmark.title)"
    if ($bookmark.title -eq "Upsert Test v2 (UPDATED)") {
        Write-Output "SUCCESS: Bookmark was updated."
    }
    else {
        Write-Output "FAILURE: Title does not match."
    }
}
else {
    Write-Output "FAILURE: Bookmark not found."
}
