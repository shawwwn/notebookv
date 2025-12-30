import { For, Suspense, SuspenseList, createMemo, createSignal, untrack, createEffect, onMount, on, onCleanup, batch } from "solid-js";
import { useParams, useLocation, useSearchParams, useNavigate, useBeforeLeave } from "@solidjs/router";
import { createStore, produce } from "solid-js/store";
import { Dynamic } from "solid-js/web"

import { Loader } from "/src/loader";
import * as Config from "/src/config.js";

import { TbCornerRightUp } from 'solid-icons/tb'
import { IoArrowBackOutline } from 'solid-icons/io'
import { TiArrowBack } from 'solid-icons/ti'
import { IoCloseOutline } from 'solid-icons/io'
import { CgSearch } from 'solid-icons/cg'
import { OcSearch3 } from 'solid-icons/oc'
import { FiChevronDown, FiChevronLeft, FiChevronRight } from 'solid-icons/fi'


// API
export async function async_fetch_quicksearch(signal, notebook_id, keyword, callback=null) {

	var url = new URL(`/api/note/${notebook_id}/search?kw=${keyword}`, window.location.href);
	var obj = await fetch(url.href, {signal})
		.then((response) => response.json())
		.then((data) => data)
		.catch(error => {
			if (error.name === 'AbortError') {

			} else {
				console.error('fetch error:', error);
			}
		});

	if (obj && callback)
		callback(obj);
	return obj;
}

export async function async_fetch_vsearch(signal, notebook_id, keyword, callback=null, k=30, search_title=true, use_fts=true) {

	var url = new URL(`/api/note/${notebook_id}/vsearch?k=${k}&title=${Number(search_title)}&fts=${Number(use_fts)}&kw=${keyword}`, window.location.href);
	var obj = await fetch(url.href, {signal})
		.then((response) => response.json())
		.then((data) => data)
		.catch(error => {
			if (error.name === 'AbortError') {

			} else {
				console.error('fetch error:', error);
			}
		});

	if (obj && callback)
		callback(obj);
	return obj;
}





class Tag {
	constructor(loc, name, start_end) {
		this.loc = loc;
		this.name = name;
		this.se = start_end;
	}
	toString() {
		return this.se==0 ? `<${this.name}>` : `</${this.name}>`
	}
}

function range2tags(range, tag_name) {
	if (!Array.isArray(range) || range.length===0)
		return [];

	var tags = [];
	for (const [s, e] of range) {
		tags.push(new Tag(s,tag_name,0), new Tag(e,tag_name,1));
	}
	return tags;
}

// group tag into idividual clusters that are separated from each other
function cluster_tags(tags) {
	var stack = [];
	var clusters = [];
	for (let tag of tags) {
		if (stack.length==0) {
			clusters.push([]);
		}

		let tag_appendices = [];
		if (tag.se==0) {
			stack.push(tag);
		} else if (tag.se==1) {
			if (stack.at(-1).name!=tag.name) {
				// tags overlap
				let idx = stack.findLastIndex(el => el.name==tag.name)
				for (let i = stack.length-1; i>idx; i--) {
					let tag_e = new Tag(tag.loc, stack[i].name, 1);
					clusters.at(-1).push(tag_e);
					let tag_s = new Tag(tag.loc, stack[i].name, 0);
					tag_appendices.unshift(tag_s);
				}
				stack.splice(idx, 1);
			} else {
				stack.pop()
			}
		}

		clusters.at(-1).push(tag);
		clusters.at(-1).push(...tag_appendices);
	}
	return clusters;
}

// merge clusters to fit window size
function merge_clusters(clusters, window_size) {
	var merged_clusters = [];
	var prev_cluster = null;
	var start = 0;
	var end = 0;
	for (let cluster of clusters) {
		let curr_cluster = (prev_cluster!=null) ? prev_cluster.concat(cluster) : cluster;
		start = curr_cluster[0].loc;
		end = curr_cluster.at(-1).loc;
		if (end-start >= window_size) {
			merged_clusters.push(curr_cluster);
			prev_cluster = null;
		} else {
			prev_cluster = curr_cluster;
		}
	}
	if (prev_cluster!=null) {
		merged_clusters.push(prev_cluster);
	}
	return merged_clusters;
}

// segment text based on number of clusters,
// then interleave segmented text and tags from each cluster to form snippets
function segment_snippets(text, clusters, window_size) {

	// calculate the range of each snippet
	var snippet_ranges = [];
	for (let i=0; i<clusters.length; i++) {
		let cluster = clusters[i];
		let start = cluster[0].loc;
		let end = cluster.at(-1).loc;
		let length = end-start;
		let padding_length = window_size-length;
		if (padding_length<=0) {
			snippet_ranges.push([start, end]);
		} else {
			let half = parseInt(padding_length/2);
			start = start - half;
			start = Math.max(start, 0)
			let prev_end = snippet_ranges[i-1]?.[1];
			if (prev_end)
				start = Math.max(start, prev_end)

			end = end + half;
			end = Math.min(end, text.length)
			let next_start = clusters[i+1]?.loc;
			if (next_start)
				end = Math.min(end, next_start)

			snippet_ranges.push([start, end]);
		}
	}

	// segment text to form snippet
	var snippets = []
	for (let j=0; j<snippet_ranges.length; j++) {
		let [s, e] = snippet_ranges[j];
		let snippet_text = text.slice(s,e);
		let snippet_segs = [];
		let pos = 0;
		for (let tag of clusters[j]) {
			tag.loc -= s; // offset to get snippet relative location
			if (pos!=tag.loc)
				snippet_segs.push(snippet_text.slice(pos, tag.loc));
			snippet_segs.push(tag);
			pos = tag.loc;
		}
		snippet_segs.push(snippet_text.slice(pos));
		if (snippet_segs.at(-1).length===0)
			snippet_segs.pop();
		snippets.push(snippet_segs);
	}
	return snippets;
}

// Generate multiple snippets from two sets of ranges(highlight/bold)
// The length of each snippet is determined by @window_size.
function generate_snippets(text, h_ranges, b_ranges, window_size=200) {
	var tags = [];
	tags = tags.concat(range2tags(h_ranges, 'hl'));
	tags = tags.concat(range2tags(b_ranges, 'b'));
	tags.sort((a, b) => a.loc-b.loc);
	var clusters = cluster_tags(tags);
	var merged_clusters = merge_clusters(clusters, window_size);
	var snippets = segment_snippets(text, merged_clusters, window_size);
	return snippets;
}

// Generate one snippet from a pair of tags
function generate_one_snippet(text, ranges) {
	var tags = range2tags(ranges, 'b');
	var snippet_segs = [];
	var pos = 0;
	for (let tag of tags) {
		if (pos!=tag.loc)
			snippet_segs.push(text.slice(pos, tag.loc));
		snippet_segs.push(tag);
		pos = tag.loc;
	}
	if (pos<text.length) {
		snippet_segs.push(text.slice(pos));
	}
	return snippet_segs;
}


export function SearchBar(props) {


	var timer;
	function _quicksearch(evt) {
		var keyword = evt.target.value;
		dom_clearbtn.classList.toggle('hidden', );
		if (!keyword.trim()) {
			// empty input
			dom_clearbtn.classList.toggle('hidden', true);
			clearTimeout(timer);
			props.request_quicksearch(""); // hidden dropdown
		} else {
			dom_clearbtn.classList.toggle('hidden', false);
			// debounce input
			clearTimeout(timer);
			timer = setTimeout(()=> {

				props.request_quicksearch(keyword);
			}, 500);
		}
	}
	
	var dom_clearbtn;
	function _clear_searchbar(evt) {
		var input = dom_clearbtn.parentElement.querySelector('input');
		input.value = "";
		batch(() => {
			props.setCache('query', "");
			props.setCache('items', []);
			props.setCache('is_hidden', true);
		});
		dom_clearbtn.classList.toggle('hidden', true);
		input.focus();
	}

	var dom_configbtn;
	function _vectorsearch_config(evt) {

	}

	function _vectorsearch(evt) {
		if(evt.keyCode != 13) {
			return;
		}
		var dom_input = evt.target;
		var keyword = dom_input.value;
		keyword = keyword.trim();
		dom_input.value = "";
		props.setCache('is_hidden', true);
		dom_clearbtn.classList.toggle('hidden', true);
		clearTimeout(timer);

		props.request_vectorsearch(keyword);
	}

	function _dropdown_item_click(item, evt) {
		props.request_open_note(item.notebookid, item.noteid);
		props.setCache("is_hidden", true);
	}

	function _dropdown_item_enter(item, evt) {
		if (event.key === "Enter") {
			event.preventDefault();
			props.request_open_note(item.notebookid, item.noteid);
			props.setCache("is_hidden", true);
		}
	}

	var dom_dropdown;
	const _dropdown_click = function (evt) {
		if (!dom_dropdown.contains(evt.target)) {
			// click outside dropdown menu
			props.setCache("is_hidden", true);
		} else if (dom_dropdown.querySelector('.searchbox').contains(evt.target)) {
			if (dom_clearbtn.contains(evt.target))
				return;
			let cache_valid = (props.cache?.query && props.cache?.query == dom_dropdown.querySelector('input')?.value);
			cache_valid && props.setCache("is_hidden", false);
		}
	};
	onMount(() => {document.documentElement.addEventListener("click", _dropdown_click)});
	onCleanup(() => {document.documentElement.removeEventListener("click", _dropdown_click)});

	return (
		<div class="dropdown" ref={dom_dropdown}>
			<div class="searchbox" class="relative">
				<div class="absolute inset-y-0 start-0 flex items-center ps-3 pointer-events-none">
					<OcSearch3 class="w-5 h-5 text-gray-500" />
				</div>
				<input id="search" onInput={_quicksearch} onKeydown={_vectorsearch} class="block w-full ps-10 px-4 py-2 text-sm text-gray-900 border border-gray-300 rounded-lg bg-gray-50 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" placeholder="Search" />
				<a ref={dom_clearbtn} onClick={_clear_searchbar} class="hidden" class="text-gray-500 absolute end-0 flex inset-y-0 items-center pe-3 hover:text-gray-900 dark:hover:text-white">
					<IoCloseOutline class="w-6 h-6" />
				</a>
			</div>
			<div class="dropdown-content" classList={{hidden: props.is_hidden}}>
				<For each={props.cache.items}>{(item, idx) => (
					<div tabindex="0" class="dropdown-item" onKeydown={[_dropdown_item_enter, item]} onClick={[_dropdown_item_click, item]}>
						<a class="title" innerHTML={item.title}></a>
						<p class="desc" innerHTML={item.desc}></p>
					</div>
				)}</For>
			</div>
		</div>
	);
}


export function SearchResultViewer(props) {

	const navigate = useNavigate();
	var thisDiv;

	// UI
	function _toggle_preview([note_id, cache_idx], evt) {
		var card = document.getElementById('note'+note_id);
		card.classList.toggle('expand');
	}

	function _open_note([notebook_id, note_id, cache_idx], evt) {
		if (this != evt.target && !evt.target.classList.contains("notetitle"))
			return;  // return when clicked on unwanted elements
		props.request_open_note(notebook_id, note_id, cache_idx);
	}

	return (
		<div ref={thisDiv} class="viewer" classList={{hidden: props.is_hidden}}>
			<Show when={props.cache.items !== undefined} fallback={<Loader />}>
			<div class="toolbar search">
				<a class="toolbtn" onClick={() => navigate(-1)}>
					<IoArrowBackOutline class="w-6 h-6 text-gray-600" style="transform: scale(0.8);" size="1rem" />
				</a>
				<div class="searchinfo">Search Results: <b>{props.cache.items?.length}</b></div>
				<a class="toolbtn" onClick={() => navigate("..")}>
					<TbCornerRightUp class="w-6 h-6 text-gray-600" size="1rem" />
					{/*<TiArrowBack class="w-6 h-6 text-gray-600" size="1rem" />*/}
				</a>
{/*				<div class="flex">
					
				</div>*/}

				
			</div>
			<div class="notelist">
				<For each={props.cache.items}>
				{(item, idx) => (
					<div class="notecard" classList={{"expand" : item.snippet_contents.length>0}} onClick={[_open_note, [item.notebookid, item.noteid, idx()]]} id={'note'+item.noteid}>
						<div class="noteheader">
							<span class="snippets notetitle" class="truncate" innerHTML={item.snippet_title}>{item.title}</span>
							<div class="notedate">{new Date(item.lastedit*1000).toLocaleString()}</div>
							<a class="toolbtn detail" class="text-gray-500" onClick={[_toggle_preview, [item.noteid, idx()]]}>
								<FiChevronDown class="w-6 h-6" />
							</a>
						</div>

						<div class="notedetail hidden">
							<div class="snippets notepreview">
								<Switch fallback={item.content.slice(0, 200)}>
									<Match when={item.snippet_contents.length>0}>
										<For each={item.snippet_contents.slice(0,5)}>
										{(snippet_content, j) =>
											<p innerHTML={snippet_content}></p>
										}
										</For>
									</Match>
								</Switch>
							</div>
						</div>
					</div>
				)}
				</For>
			</div>
			</Show>
		</div>
	);
}



export function SearchPage(props) {
	const navigate = useNavigate();
	const params = useParams();
	const location = useLocation();
	window.loc = location;
	const [searchParams, setSearchParams] = useSearchParams();
	window.searchParams = searchParams;
	window.setSearchParams = setSearchParams;

	const [quickSearchCache, setQuickSearchCache] = createStore({
		is_hidden: true,
		items: []
	});
	const [vectorSearchCache, setVectorSearchCache] = createStore({
		is_hidden: false,
		items: undefined,
		kw: undefined,
		k: undefined,
	});


	var notebookid = parseInt(params.notebookid);




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

		if (!notebookid) {
			return;
		}

		qs_controller.abort(); // abort previous quicksearch request
		qs_controller = new AbortController();
		let signal = qs_controller.signal;
		async_fetch_quicksearch(signal, notebookid, keyword, (data) => {
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

	// call vectorsearch API
	var vs_controller = new AbortController();
	function vectorsearch(keyword, k) {

		if (!keyword.trim() || !notebookid) {
			return;
		}

		// clear previous result
		batch(() => {
			setVectorSearchCache('kw', undefined);
			setVectorSearchCache('k', undefined);
			setVectorSearchCache('items', undefined);
		});

		// parse api returns to the format of SearchPage cache
		function parse_vsearch_result(results) {
			var rankings = [];
			for (let item of results) {
				let snippet_title = (item?.title_pos) ? generate_one_snippet(item.title, item.title_pos).join('') : item.title;
				snippet_title = (item?.title_vmatch===true) ? `<hl>${snippet_title}</hl>` : snippet_title;
				let h_ranges = (item?.chunk_pos) ? item.chunk_pos : [];
				let b_ranges = (item?.content_pos) ? item.content_pos : [];
				let snippets = generate_snippets(item.content, h_ranges, b_ranges, 200);
				let snippet_contents = snippets.map(sp => sp.join('')); // render each snippet to text
				rankings.push({
					rank: item.rank,
					noteid: item.noteid,
					notebookid: notebookid,
					lastedit: item.lastedit,
					title: item.title,
					content: item.content,
					snippet_title: snippet_title,
					snippet_contents: snippet_contents,
				});
			}
			return rankings;
		}

		vs_controller.abort(); // abort previous vectorsearch request
		vs_controller = new AbortController();
		let signal = vs_controller.signal;
		async_fetch_vsearch(signal, notebookid, keyword, (data) => {
			if (!data || data['code']!==200) {

				return;
			}


			var results = data['content']['ranking'];
			var items = parse_vsearch_result(results);

			batch(() => {
				setVectorSearchCache('is_hidden', false);
				setVectorSearchCache('items', items);
				setVectorSearchCache('kw', keyword);
				setVectorSearchCache('k', k);
			});
		}, k);
	}

	// change search params to trigger vectorsearch from memo
	function _trigger_vectorseach(keyword) {
		vs_controller.abort(); // abort previous vectorsearch request
		setSearchParams({kw: keyword});
	}

	function open_note(notebook_id, note_id, cache_idx=null) {

		return navigate(`/note/${notebook_id}/${note_id}`);
	}

	// run on navigation
	createMemo(on(()=>[searchParams.kw, searchParams.k], (arr, prev_arr) => {
		const keyword = searchParams.kw;
		const k = searchParams.k || 5;
		console.debug("searchParams changed: ", searchParams);

		if (keyword && keyword!="") {
			vectorsearch(searchParams.kw);
		} else {
			navigate("..");
		}
	}));



	return (
		<div class="container">

			<div class="topbar">
				<div class="logo">
					<h1 class="title">This Is Notebook #{notebookid}</h1>
				</div>
				<SearchBar cache={quickSearchCache}
					setCache={setQuickSearchCache}
					request_quicksearch={quicksearch}
					request_vectorsearch={_trigger_vectorseach}
					request_open_note={open_note}
					is_hidden={quickSearchCache.is_hidden}
				/>
			</div>

			<SearchResultViewer cache={vectorSearchCache}
				setCache={setVectorSearchCache}
				request_open_note={open_note}
				is_hidden={vectorSearchCache.is_hidden}
			/>

		</div>
	);
}

export default SearchPage;
