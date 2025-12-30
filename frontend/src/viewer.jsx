import { For, Suspense, SuspenseList, createMemo, createSignal, untrack } from "solid-js";
import { useParams, useLocation, useSearchParams, useNavigate, useBeforeLeave } from "@solidjs/router";
import { createStore, produce } from "solid-js/store";

import { FaSolidAngleDown } from 'solid-icons/fa'
import { FaSolidAnglesDown } from 'solid-icons/fa'
import { IoClose } from 'solid-icons/io'
import { FiChevronDown, FiChevronLeft, FiChevronRight } from 'solid-icons/fi'
import { BiSolidEdit } from 'solid-icons/bi'
import { AiOutlinePlus } from 'solid-icons/ai'


export function NotebookViewer(props) {


	// UI
	function _open_note([note_id, cache_idx], evt) {
		if (this != evt.target && !evt.target.classList.contains("notetitle"))
			return;  // return when clicked on unwanted elements
		props.request_open_note(props.cache.notebookid, note_id, cache_idx);
	}

	function _delete_note([note_id, cache_idx], evt) {
		props.request_delete_note(props.cache.notebookid, note_id, cache_idx);
	}

	function _toggle_preview([note_id, cache_idx], evt) {
		var card = document.getElementById('note'+note_id);
		card.classList.toggle('expand');
	}

	function _next_page(evt) {
		props.request_next_page();
	}

	function _prev_page(evt) {
		props.request_prev_page();
	}

	function _gen_page_count() {
		if (!props.cache?.page)
			return "";
		var start = (props.cache.page-1) * props.cache.page_size;
		if (start+1 > props.cache.total_n)
			return ""
		var end = start + props.cache.page_n;
		var text = `${start+1}-${end} of ${props.cache.total_n}`;
		return text;
	}

	function _create_note() {
		props.request_create_note(props.cache.notebookid);
	}

	return (
		<div class="viewer" classList={{hidden: props.is_hidden}}>
			<div class="toolbar">
				<div class="tabs flex items-center space-x-4">
					<div onClick={_create_note} class="tab active"><AiOutlinePlus class="w-6 h-6 mr-2" />New</div>
				</div>
				<span class="pageinfo">{_gen_page_count}</span>
				<div class="-space-x-px inline-flex rounded shadow-sm mr-4">
					<a onClick={_prev_page} class="rounded-s inline-flex items-center justify-center text-body rounded-s-base box-border border border-default hover:bg-gray-100 focus:ring focus:outline-none">
						<FiChevronLeft class="w-6 h-6" />
					</a>
					<a onClick={_next_page} class="rounded-e inline-flex items-center justify-center text-body rounded-s-base box-border border border-default hover:bg-gray-100 focus:ring focus:outline-none">
						<FiChevronRight class="w-6 h-6" />
					</a>
				</div>
			</div>
			<div class="notelist">
				<For each={props.cache.notes}>
					{(note, idx) => (
						<Show when={note}>
						<div class="notecard" onClick={[_open_note, [note.noteid, idx()]]} id={'note'+note.noteid} class="cursor-pointer" >
							<div class="noteheader">
								<span class="notetitle" class="truncate">{note.title}</span>
								<span class="notedate">{new Date(note.lastedit*1000).toLocaleString()}</span>
								<a class="toolbtn detail" class="text-gray-500" onClick={[_toggle_preview, [note.noteid, idx()]]}>
									<FiChevronDown class="w-6 h-6" />
								</a>
							</div>

							<div class="notedetail hidden">
								<div class="notepreview">{note.textcontent.slice(0,280)}</div>
									<a class="toolbtn delete" class="text-red-800" onClick={[_delete_note, [note.noteid, idx()]]}>
										<IoClose class="w-6 h-6" />
									</a>
							</div>
						</div>
						</Show>
					)}
				</For>
			</div>
		</div>
	);
}


export default NotebookViewer;
