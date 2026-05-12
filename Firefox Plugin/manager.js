document.addEventListener('DOMContentLoaded', () => {
    // State
    let state = {
        bookmarks: [],
        total: 0,
        skip: 0,
        limit: 50,
        tagPrefix: null,
        query: null,
        selectedBookmarkId: null,
        selectedBookmarkIds: new Set(),
        tags: []
    };

    // DOM Elements
    const tagTree = document.getElementById('tag-tree');
    const tableBody = document.getElementById('bookmark-table-body');
    const prevPageBtn = document.getElementById('prev-page-btn');
    const nextPageBtn = document.getElementById('next-page-btn');
    const pageInfo = document.getElementById('page-info');
    const currentViewTitle = document.getElementById('current-view-title');
    const searchInput = document.getElementById('manager-search-input');
    
    // Detail Pane Elements
    const detailPane = document.getElementById('detail-pane');
    const editForm = document.getElementById('edit-form');
    const emptyState = detailPane.querySelector('.empty-state');
    const editTitle = document.getElementById('edit-title');
    const editUrl = document.getElementById('edit-url');
    const editUrlLink = document.getElementById('edit-url-link');
    const editTags = document.getElementById('edit-tags');
    const saveEditBtn = document.getElementById('save-edit-btn');
    const deleteSingleBtn = document.getElementById('delete-single-btn');

    // Bulk Actions
    const selectAllCheckbox = document.getElementById('select-all-checkbox');
    const bulkToolbar = document.getElementById('bulk-toolbar');
    const selectedCountLabel = document.getElementById('selected-count-label');
    const bulkAddTagBtn = document.getElementById('bulk-add-tag-btn');
    const bulkRemoveTagBtn = document.getElementById('bulk-remove-tag-btn');
    const bulkDeleteBtn = document.getElementById('bulk-delete-btn');

    // Modals
    const deleteTagModal = document.getElementById('delete-tag-modal');
    const deleteTagDisplay = document.getElementById('delete-tag-display');
    const removeTagOnlyBtn = document.getElementById('remove-tag-only-btn');
    const deleteBookmarksWithTagBtn = document.getElementById('delete-bookmarks-with-tag-btn');
    const cancelDeleteTagBtn = document.getElementById('cancel-delete-tag-btn');
    let currentDeleteTag = null;

    // Modals
    const renameTagModal = document.getElementById('rename-tag-modal');
    const oldPrefixDisplay = document.getElementById('old-prefix-display');
    const newPrefixInput = document.getElementById('new-prefix-input');
    const cancelRenameBtn = document.getElementById('cancel-rename-btn');
    const confirmRenameBtn = document.getElementById('confirm-rename-btn');
    let currentRenamePrefix = null;
    
    const contentPreviewBox = document.getElementById('content-preview-box');

    // Helper
    function escapeHTML(str) {
        if (!str) return '';
        return str.replace(/[&<>'"]/g, 
            tag => ({
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                "'": '&#39;',
                '"': '&quot;'
            }[tag] || tag)
        );
    }

    // 1. Initialization
    async function init() {
        // Ensure token is set
        const stored = await browser.storage.local.get('authToken');
        if (stored.authToken) {
            window.api.setToken(stored.authToken);
            await loadTags();
            await loadBookmarks();
        } else {
            document.body.innerHTML = '<div style="padding: 20px;">Please login via the extension popup first.</div>';
        }
    }

    // 2. Data Loading
    async function loadTags() {
        try {
            const rawTags = await window.api.getTags();
            state.tags = rawTags;
            renderTagTree();
        } catch (error) {
            console.error("Failed to load tags:", error);
            tagTree.innerHTML = `<div class="loading-state">Error loading tags.</div>`;
        }
    }

    async function loadBookmarks() {
        try {
            tableBody.innerHTML = '<tr><td colspan="5" style="text-align: center;">Loading...</td></tr>';
            const response = await window.api.getAllBookmarks(state.skip, state.limit, state.tagPrefix, state.query);
            state.bookmarks = response.items;
            state.total = response.total;
            
            // Reset selections
            state.selectedBookmarkIds.clear();
            updateBulkToolbar();
            updateDetailPane();

            renderTable();
            updatePagination();
        } catch (error) {
            console.error("Failed to load bookmarks:", error);
            tableBody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: red;">Error: ${error.message}</td></tr>`;
        }
    }

    // 3. Rendering
    function renderTagTree() {
        tagTree.innerHTML = '';

        // "All Bookmarks" node
        const allNode = createTreeNode('All Bookmarks', null, !state.tagPrefix);
        tagTree.appendChild(allNode);

        // "Untagged" node
        const untaggedNode = createTreeNode('Untagged', 'untagged', state.tagPrefix === 'untagged');
        tagTree.appendChild(untaggedNode);

        // Build hierarchy
        const tree = {};
        state.tags.forEach(({ tag, count }) => {
            const parts = tag.split('/');
            let current = tree;
            let currentPath = '';
            
            parts.forEach((part, i) => {
                currentPath = currentPath ? `${currentPath}/${part}` : part;
                if (!current[part]) {
                    current[part] = { _path: currentPath, _count: 0, _children: {} };
                }
                if (i === parts.length - 1) {
                     current[part]._count += count; // add exact matches
                }
                current = current[part]._children;
            });
        });

        // Function to recursively add nodes
        function addNodes(container, obj, level = 0) {
            for (const key in obj) {
                const nodeData = obj[key];
                // Calculate total count (node + children)
                const totalCount = calculateTotalCount(nodeData);

                const isActive = state.tagPrefix === nodeData._path;
                const nodeEl = createTreeNode(key, nodeData._path, isActive, totalCount, level);
                container.appendChild(nodeEl);
                
                // Recursively add children
                if (Object.keys(nodeData._children).length > 0) {
                    addNodes(container, nodeData._children, level + 1);
                }
            }
        }
        
        function calculateTotalCount(nodeData) {
            let sum = nodeData._count;
            for(let key in nodeData._children) {
                 sum += calculateTotalCount(nodeData._children[key]);
            }
            return sum;
        }

        addNodes(tagTree, tree);
    }

    function createTreeNode(label, path, isActive, count = null, level = 0) {
        const div = document.createElement('div');
        div.className = `tree-node ${isActive ? 'active' : ''}`;
        div.style.paddingLeft = `${10 + (level * 15)}px`;
        
        let html = `<span class="icon">${path === null ? '📁' : '🏷️'}</span> <span class="label">${escapeHTML(label)}</span>`;
        if (count !== null) {
            html += `<span class="count">${count}</span>`;
        }
        
        if (path !== null && path !== 'untagged') {
            html += `
                <div class="actions">
                    <button class="icon-btn rename-tag-btn" title="Rename" data-path="${escapeHTML(path)}">✏️</button>
                    <button class="icon-btn delete-tag-btn" title="Delete" data-path="${escapeHTML(path)}" style="color: #e53e3e;">🗑️</button>
                </div>
            `;
        }
        
        div.innerHTML = html;
        
        div.addEventListener('click', (e) => {
            if (e.target.closest('.rename-tag-btn')) {
                e.stopPropagation();
                openRenameModal(path);
                return;
            }
            if (e.target.closest('.delete-tag-btn')) {
                e.stopPropagation();
                openDeleteTagModal(path);
                return;
            }
            
            state.tagPrefix = path;
            state.skip = 0; // Reset pagination
            currentViewTitle.textContent = path ? `Tag: ${path}` : 'All Bookmarks';
            loadBookmarks();
            renderTagTree(); // Update active state
        });
        
        // Drag and drop support
        if (path !== null && path !== 'untagged') {
            div.addEventListener('dragover', (e) => {
                e.preventDefault();
                div.style.backgroundColor = '#edf2f7';
            });
            div.addEventListener('dragleave', (e) => {
                div.style.backgroundColor = '';
            });
            div.addEventListener('drop', async (e) => {
                e.preventDefault();
                div.style.backgroundColor = '';
                
                const bookmarkId = e.dataTransfer.getData('text/plain');
                if (bookmarkId) {
                    const idsToMove = state.selectedBookmarkIds.has(bookmarkId) ? Array.from(state.selectedBookmarkIds) : [bookmarkId];
                    try {
                        await window.api.bulkAddTag(idsToMove, path);
                        await loadTags();
                        await loadBookmarks();
                    } catch (err) {
                        alert("Failed to add tag: " + err.message);
                    }
                }
            });
        }
        
        return div;
    }

    function renderTable() {
        tableBody.innerHTML = '';
        if (state.bookmarks.length === 0) {
            tableBody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: #718096; padding: 30px;">No bookmarks found.</td></tr>';
            return;
        }

        state.bookmarks.forEach(bookmark => {
            const tr = document.createElement('tr');
            tr.setAttribute('draggable', 'true');
            tr.addEventListener('dragstart', (e) => {
                e.dataTransfer.setData('text/plain', bookmark.id);
            });
            if (state.selectedBookmarkIds.has(bookmark.id)) tr.classList.add('selected');
            
            const dateStr = new Date(bookmark.created_at || Date.now()).toLocaleDateString();
            const tagsHtml = bookmark.tags.map(t => `<span class="tag-chip">${escapeHTML(t)}</span>`).join('');
            
            tr.innerHTML = `
                <td><input type="checkbox" class="row-checkbox" value="${bookmark.id}" ${state.selectedBookmarkIds.has(bookmark.id) ? 'checked' : ''}></td>
                <td><strong>${escapeHTML(bookmark.title || 'Untitled')}</strong></td>
                <td><a href="${escapeHTML(bookmark.url)}" target="_blank" class="external-link" style="margin:0">${escapeHTML(bookmark.url)}</a></td>
                <td>${tagsHtml}</td>
                <td>${dateStr}</td>
            `;

            // Row click for selection (excluding checkbox and links)
            tr.addEventListener('click', (e) => {
                if (e.target.type === 'checkbox' || e.target.tagName === 'A') return;
                
                // Highlight row and show details
                tableBody.querySelectorAll('tr').forEach(row => row.style.backgroundColor = '');
                tr.style.backgroundColor = '#ebf4ff';
                
                state.selectedBookmarkId = bookmark.id;
                updateDetailPane(bookmark);
            });

            // Checkbox change
            const checkbox = tr.querySelector('.row-checkbox');
            checkbox.addEventListener('change', (e) => {
                if (e.target.checked) {
                    state.selectedBookmarkIds.add(bookmark.id);
                    tr.classList.add('selected');
                } else {
                    state.selectedBookmarkIds.delete(bookmark.id);
                    tr.classList.remove('selected');
                }
                updateBulkToolbar();
            });

            tableBody.appendChild(tr);
        });
    }

    function updatePagination() {
        const totalPages = Math.ceil(state.total / state.limit) || 1;
        const currentPage = Math.floor(state.skip / state.limit) + 1;
        
        pageInfo.textContent = `Page ${currentPage} of ${totalPages} (${state.total} total)`;
        
        prevPageBtn.disabled = currentPage <= 1;
        nextPageBtn.disabled = currentPage >= totalPages;
    }

    function updateDetailPane(bookmark = null) {
        if (!bookmark) {
            emptyState.style.display = 'block';
            editForm.style.display = 'none';
            return;
        }

        emptyState.style.display = 'none';
        editForm.style.display = 'block';

        editTitle.value = bookmark.title || '';
        editUrl.value = bookmark.url;
        editUrlLink.href = bookmark.url;
        editTags.value = bookmark.tags.join(', ');
        contentPreviewBox.textContent = bookmark.content_markdown || 'No content available.';
    }

    function updateBulkToolbar() {
        const count = state.selectedBookmarkIds.size;
        if (count > 0) {
            bulkToolbar.style.display = 'flex';
            selectedCountLabel.textContent = `${count} selected`;
            selectAllCheckbox.checked = count === state.bookmarks.length && count > 0;
        } else {
            bulkToolbar.style.display = 'none';
            selectAllCheckbox.checked = false;
        }
    }

    // 4. Event Listeners
    
    // Pagination
    prevPageBtn.addEventListener('click', () => {
        if (state.skip > 0) {
            state.skip -= state.limit;
            loadBookmarks();
        }
    });

    nextPageBtn.addEventListener('click', () => {
        if (state.skip + state.limit < state.total) {
            state.skip += state.limit;
            loadBookmarks();
        }
    });

    // Search
    let searchDebounce;
    searchInput.addEventListener('input', (e) => {
        clearTimeout(searchDebounce);
        searchDebounce = setTimeout(() => {
            state.query = e.target.value.trim() || null;
            state.skip = 0;
            loadBookmarks();
        }, 300);
    });

    // Bulk Select All
    selectAllCheckbox.addEventListener('change', (e) => {
        const checked = e.target.checked;
        state.selectedBookmarkIds.clear();
        
        if (checked) {
            state.bookmarks.forEach(b => state.selectedBookmarkIds.add(b.id));
        }
        
        renderTable(); // Re-render to update checkboxes and row classes
        updateBulkToolbar();
    });

    // Save Edit
    saveEditBtn.addEventListener('click', async () => {
        if (!state.selectedBookmarkId) return;
        
        const newTitle = editTitle.value.trim();
        const newTags = editTags.value.split(',').map(t => t.trim()).filter(t => t);
        
        const originalText = saveEditBtn.textContent;
        saveEditBtn.textContent = 'Saving...';
        saveEditBtn.disabled = true;

        try {
            await window.api.updateBookmark(state.selectedBookmarkId, {
                title: newTitle,
                tags: newTags
            });
            
            saveEditBtn.textContent = 'Saved!';
            saveEditBtn.style.backgroundColor = '#48bb78';
            
            // Reload data
            await loadTags();
            await loadBookmarks();
            
        } catch (error) {
            console.error("Save failed:", error);
            alert("Failed to save: " + error.message);
        } finally {
            setTimeout(() => {
                saveEditBtn.textContent = originalText;
                saveEditBtn.style.backgroundColor = '';
                saveEditBtn.disabled = false;
            }, 1500);
        }
    });

    // Single Delete
    deleteSingleBtn.addEventListener('click', async () => {
        if (!state.selectedBookmarkId) return;
        if (!confirm("Are you sure you want to delete this bookmark?")) return;
        
        try {
            await window.api.deleteBookmark(state.selectedBookmarkId);
            state.selectedBookmarkId = null;
            await loadTags();
            await loadBookmarks();
        } catch (error) {
            alert("Failed to delete: " + error.message);
        }
    });

    // Bulk Delete
    bulkDeleteBtn.addEventListener('click', async () => {
        if (state.selectedBookmarkIds.size === 0) return;
        if (!confirm(`Are you sure you want to delete ${state.selectedBookmarkIds.size} bookmarks?`)) return;
        
        const originalText = bulkDeleteBtn.innerHTML;
        bulkDeleteBtn.textContent = 'Deleting...';
        bulkDeleteBtn.disabled = true;

        try {
            await window.api.bulkDelete(Array.from(state.selectedBookmarkIds));
            state.selectedBookmarkIds.clear();
            await loadTags();
            await loadBookmarks();
        } catch (error) {
            alert("Failed to bulk delete: " + error.message);
        } finally {
            bulkDeleteBtn.innerHTML = originalText;
            bulkDeleteBtn.disabled = false;
        }
    });

    bulkAddTagBtn.addEventListener('click', async () => {
        if (state.selectedBookmarkIds.size === 0) return;
        const tag = prompt("Enter tag to add to selected bookmarks:");
        if (!tag) return;
        
        try {
            await window.api.bulkAddTag(Array.from(state.selectedBookmarkIds), tag);
            await loadTags();
            await loadBookmarks();
        } catch (err) {
            alert("Failed to add tag: " + err.message);
        }
    });

    bulkRemoveTagBtn.addEventListener('click', async () => {
        if (state.selectedBookmarkIds.size === 0) return;
        const tag = prompt("Enter tag to remove from selected bookmarks:");
        if (!tag) return;
        
        try {
            await window.api.bulkRemoveTag(Array.from(state.selectedBookmarkIds), tag);
            await loadTags();
            await loadBookmarks();
        } catch (err) {
            alert("Failed to remove tag: " + err.message);
        }
    });

    // Rename Tag Modal
    function openRenameModal(oldPrefix) {
        currentRenamePrefix = oldPrefix;
        oldPrefixDisplay.textContent = oldPrefix;
        newPrefixInput.value = oldPrefix;
        renameTagModal.classList.add('active');
        newPrefixInput.focus();
    }

    cancelRenameBtn.addEventListener('click', () => {
        renameTagModal.classList.remove('active');
        currentRenamePrefix = null;
    });

    confirmRenameBtn.addEventListener('click', async () => {
        const newPrefix = newPrefixInput.value.trim();
        if (!newPrefix || newPrefix === currentRenamePrefix) {
            renameTagModal.classList.remove('active');
            return;
        }

        const originalText = confirmRenameBtn.textContent;
        confirmRenameBtn.textContent = 'Renaming...';
        confirmRenameBtn.disabled = true;

        try {
            await window.api.bulkUpdateTags(currentRenamePrefix, newPrefix);
            renameTagModal.classList.remove('active');
            
            // If we were filtering by the old prefix, update to the new one
            if (state.tagPrefix && state.tagPrefix.startsWith(currentRenamePrefix)) {
                state.tagPrefix = newPrefix + state.tagPrefix.substring(currentRenamePrefix.length);
            }
            
            await loadTags();
            await loadBookmarks();
        } catch (error) {
            alert("Rename failed: " + error.message);
        } finally {
            confirmRenameBtn.textContent = originalText;
            confirmRenameBtn.disabled = false;
        }
    });

    // Delete Tag Modal
    function openDeleteTagModal(tag) {
        currentDeleteTag = tag;
        deleteTagDisplay.textContent = tag;
        deleteTagModal.classList.add('active');
    }

    cancelDeleteTagBtn.addEventListener('click', () => {
        deleteTagModal.classList.remove('active');
        currentDeleteTag = null;
    });

    removeTagOnlyBtn.addEventListener('click', async () => {
        if (!currentDeleteTag) return;
        removeTagOnlyBtn.disabled = true;
        try {
            const res = await window.api.getAllBookmarks(0, 1000, currentDeleteTag);
            if (res.items && res.items.length > 0) {
                const ids = res.items.map(b => b.id);
                await window.api.bulkRemoveTag(ids, currentDeleteTag);
            }
            deleteTagModal.classList.remove('active');
            
            if (state.tagPrefix === currentDeleteTag) state.tagPrefix = null;
            await loadTags();
            await loadBookmarks();
        } catch (err) {
            alert("Failed: " + err.message);
        } finally {
            removeTagOnlyBtn.disabled = false;
        }
    });

    deleteBookmarksWithTagBtn.addEventListener('click', async () => {
        if (!currentDeleteTag) return;
        deleteBookmarksWithTagBtn.disabled = true;
        try {
            const res = await window.api.getAllBookmarks(0, 1000, currentDeleteTag);
            if (res.items && res.items.length > 0) {
                const ids = res.items.map(b => b.id);
                await window.api.bulkDelete(ids);
            }
            deleteTagModal.classList.remove('active');
            
            if (state.tagPrefix === currentDeleteTag) state.tagPrefix = null;
            await loadTags();
            await loadBookmarks();
        } catch (err) {
            alert("Failed: " + err.message);
        } finally {
            deleteBookmarksWithTagBtn.disabled = false;
        }
    });

    // Kickoff
    init();
});
