$response = Invoke-RestMethod -Uri "http://localhost:8000/recent" -Method Get
Write-Output "Recent Bookmarks:"
foreach ($bookmark in $response) {
    Write-Output " - [$($bookmark.status)] $($bookmark.title) ($($bookmark.url))"
}
