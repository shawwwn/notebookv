import { For, Suspense, SuspenseList, createMemo, createSignal, untrack, createEffect, onMount, on, onCleanup, batch } from "solid-js";
import { useParams, useLocation, useSearchParams, useNavigate, useBeforeLeave } from "@solidjs/router";
import { createStore, produce } from "solid-js/store";
import { Dynamic } from "solid-js/web";

import NoteEditor from "/src/editor";
import { NotebookViewer } from "/src/viewer";
import { SearchBar, async_fetch_quicksearch } from "/src/search";

import * as Config from "/src/config.js";


// fetch from api
var fetching_noteook = Promise.resolve(true);
async function async_fetch_notebook(notebook_id, callback=null, page=1, pagesize=50) {
	page = (page === null) ? 1 : page;
	await fetching_noteook;
	var fetching_noteook_done = await new Promise(r => {
		fetching_noteook = new Promise(rr => r(rr));
	});

	var url = new URL(`/api/note/${notebook_id}/get`, window.location.href);
	url.searchParams.set('page', page);
	url.searchParams.set('pagesize', pagesize);
	var obj = await fetch(url.href)
		.then((response) => response.json())
		.then((data) => data)
		.catch(error => {
			console.error('fetch error:', error);
		});
	if (obj && callback) {
		callback(obj);
	}
	fetching_noteook_done(true);
	return obj;
}

async function async_fetch_note(notebook_id, note_id, callback=null) {
	if (!note_id)
		return;
	await fetching_noteook;

	var url = new URL(`/api/note/${notebook_id}/${note_id}/get`, window.location.href);
	var obj = await fetch(url.href)
		.then((response) => response.json())
		.then((data) => data)
		.catch(error => {
			console.error('fetch error:', error);
		});
	if (obj && callback) {
		callback(obj);
	}
	return obj;
}

export function NoteBookPage() {
	const navigate = useNavigate();
	const params = useParams();

	// local data store
	const [notebookCache, setNotebookCache] = createStore({
		is_hidden: !!params.noteid,
		dirty: false
	});
	window.setNotebookCache = setNotebookCache;
	window.notebookCache = notebookCache;
	const [noteCache, setNoteCache] = createStore({
		is_hidden: !params.noteid,
	});
	window.setNoteCache = setNoteCache;
	window.noteCache = noteCache;
	const [quickSearchCache, setQuickSearchCache] = createStore({
		is_hidden: true,
		items: []
	});
	window.quickSearchCache = quickSearchCache;
	window.setQuickSearchCache = setQuickSearchCache;


	// logout current user
	function user_logout() {
		fetch('/api/logout', {
			method: 'POST',
		})
		.then(response => response.json())
		.then(data => {
			if (data?.status) {
				// data returned
				localStorage.removeItem('user');
				navigate(`/login`);
			} else {
				console.error('Error: failed to logout');
			}
		});
	}

	// call quicksearch API
	var qs_controller = new AbortController();
	function quicksearch(keyword) {


		// empty input
		if (!keyword.trim()) {
			qs_controller.abort(); // abort previous quicksearch request
			batch(() => {
				setQuickSearchCache('query', "");
				setQuickSearchCache('items', []);
				setQuickSearchCache('is_hidden', true);
			});
			return;
		}

		var notebook_id = notebookCache?.notebookid ? notebookCache.notebookid : params.notebookid;
		if (!notebook_id) {
			return;
		}

		qs_controller.abort(); // abort previous quicksearch request
		qs_controller = new AbortController();
		let signal = qs_controller.signal;
		async_fetch_quicksearch(signal, notebook_id, keyword, (data) => {
			if (!data || data['code']!==200) {

				return;
			}

			batch(() => {
				setQuickSearchCache('query', data.content.query);
				setQuickSearchCache('items', data.content.result);
				setQuickSearchCache('is_hidden', false);
			});
		});
	}

	// goto search page
	function goto_vectorsearch(keyword) {
		qs_controller.abort(); // abort previous quicksearch request
		if (!keyword.trim()) {
			return;
		}

		var notebook_id = notebookCache?.notebookid ? notebookCache.notebookid : params.notebookid;
		if (!notebook_id) {
			return;
		}

		console.debug("goto vector search page");
		navigate(`/note/${notebook_id}/search?kw=${keyword}`);
	}

	// create a new note and goto note page
	function create_note(notebook_id) {
		if (!notebook_id) {
			notebook_id = params.notebookid;
		}
		console.debug(`request create_note(${notebook_id})`);

		var payload = {
			title: "Untitled",
			textcontent: "...",
		};
		fetch(`/api/note/${notebook_id}/new`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(payload)
		})
		.then(response => response.json())
		.then(data => {
			if (data?.code === 200) {
				// success
				setNotebookCache('dirty', true);
				navigate(`/note/${data.content.notebookid}/${data.content.noteid}`);
			} else {
				console.error('Error: failed to create note');
			}
		});
	}

	// goto note page
	function open_note(notebook_id, note_id, cache_idx=null) {
		console.debug(`request open_note(${notebook_id}/${note_id})`);
		let note = notebookCache.notes?.find((n, i) => n?.noteid == note_id);
		if (note) {
			console.debug(`preload note#${notebook_id}/${note_id} from cache`);
			setNoteCache(note);
			setNoteCache('dirty', false);
		}
		return navigate(`/note/${notebook_id}/${note_id}`);
	}

	// call API to update note
	function update_note(title, textcontent) {
		var note = {
			notebookid: parseInt(noteCache.notebookid),
			noteid: parseInt(noteCache.noteid),
			title: title,
			textcontent: textcontent,
		};

		(async (payload) => {
			var url = new URL(`/api/note/${noteCache.notebookid}/${noteCache.noteid}/update`, window.location.href);
			var obj = await fetch(url.href, {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify(payload)
				})
				.then((response) => response.json())
				.then((data) => data);
			if (obj && obj.code===200) {
				setNoteCache('dirty', false);
			}
		})(note);

		// update notebook cache (if any)
		if (noteCache.notebookid === notebookCache.notebookid) {
			let idx = notebookCache?.notes.findIndex(note => note?.noteid===noteCache?.noteid);
			if (idx!=undefined) {
				setNotebookCache('notes', idx, 'title', title);
				setNotebookCache('notes', idx, 'textcontent', textcontent);
			}
		}
	}

	// call API to delete note
	function delete_note(notebook_id, note_id, cache_idx=null) {
		var userResponse = confirm("Do you want to delete this note?");
		if (!userResponse) {
			return false;
		}

		// purge cache
		if (notebook_id == notebookCache.notebookid) {
			if (cache_idx !== null) {
				setNotebookCache('notes', cache_idx, undefined);
			} else {
				setNotebookCache('notes', (note) => (note?.noteid==note_id), undefined);
			}
		}

		// api
		(async () => {
			var url = new URL(`/api/note/${notebook_id}/${note_id}/delete`, window.location.href);
			var obj = await fetch(url.href)
				.then((response) => response.json())
				.then((data) => data);

		})();

		return true;
	}

	// goto next/prev page
	function page_nav(icrement) {
		var next_page_i = notebookCache.page + icrement;
		var max_page = Math.ceil(notebookCache.total_n/notebookCache.page_size);
		if (next_page_i<=0 || next_page_i>max_page) {
			return;
		}
		return navigate(`/note/${notebookCache.notebookid}?page=${next_page_i}`);
	}

	//
	// First-time Initialization
	//


	// run on navigation
	const location = useLocation();
	var prev_notebookid = params.notebookid;
	var prev_noteid = params.noteid;
	createEffect(on(()=>location.pathname+location.search, (pathname, prevPathname) => {
		let search_params = new URLSearchParams(location.search);
		let page_i = search_params.get('page') || 1;
		let notebookcache_valid = (params.notebookid === notebookCache.notebookid && notebookCache.page === page_i && notebookCache?.dirty !== true);
		let notecache_valid = (params.noteid==noteCache.noteid && params.notebookid==noteCache.notebookid);


		setNotebookCache('is_hidden', !!params.noteid);
		setNoteCache('is_hidden', !params.noteid);

		// handle content display during in-app navigation
		if (params.noteid) {
			if (notecache_valid) {

			} else {
				async_fetch_note(params.notebookid, params.noteid, (data) => {
					if (data?.code === 200) {
						setNoteCache(data.content);
						setNoteCache('dirty', false);
					} else {

					}
				});
			}
		} else {
			if (notebookcache_valid) {

			} else {
				async_fetch_notebook(params.notebookid, (data) => {
					if (data?.code === 200) {
						setNotebookCache(data.content);
					} else {

					}
				}, page_i);
			}
		}

		prev_notebookid = params.notebookid;
		prev_noteid = params.noteid;
	}));



	return (
		<div class="container">

			<div class="topbar">
				<div class="logo flex w-full justify-between">
					<h1 class="title">This Is Notebook #{notebookCache.notebookid || noteCache.notebookid}</h1>
					<a onClick={user_logout} class="ms-2 rounded-full p-1 self-center text-center text-gray-500 hover:text-black hover:dark:text-white hover:bg-gray-200 hover:dark:bg-gray-800;">
						<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
							<path stroke-linecap="round" stroke-linejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
						</svg>
					</a>
				</div>
				<SearchBar cache={quickSearchCache}
					setCache={setQuickSearchCache}
					request_quicksearch={quicksearch}
					request_vectorsearch={goto_vectorsearch}
					request_open_note={open_note}
					is_hidden={quickSearchCache.is_hidden}
				/>
			</div>

			<NotebookViewer cache={notebookCache}
				request_create_note={create_note}
				request_open_note={open_note}
				request_delete_note={delete_note}
				request_next_page={() => page_nav(1)}
				request_prev_page={() => page_nav(-1)}
				is_hidden={notebookCache.is_hidden}
			/>

			<NoteEditor cache={noteCache}
				setCache={setNoteCache}
				request_open_note={open_note}
				request_update_note={update_note}
				request_delete_note={delete_note}
				is_hidden={noteCache.is_hidden}
			/>

		</div>
	);
}

export default NoteBookPage;
