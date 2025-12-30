import { For, Suspense, SuspenseList, createMemo, createSignal, untrack } from "solid-js";
import { useParams, useLocation, useSearchParams, useNavigate, useBeforeLeave } from "@solidjs/router";
import { createStore, produce } from "solid-js/store";

import { RiSystemDeleteBin5Line } from 'solid-icons/ri'
import { RiDeviceSave3Line } from 'solid-icons/ri'
import { IoArrowUndoSharp } from 'solid-icons/io'

import { Loader } from "/src/loader";


function NoteEditor(props) {
	const navigate = useNavigate();
	const params = useParams();

	var dom_title;
	var dom_content;

	function ask_before_deletion() {
		var ret = props.request_delete_note(props.cache.notebookid, props.cache.noteid);
		if (ret) {
			props.setCache('is_hidden', true);
			props.setCache('noteid', undefined);
			navigate(-1);
		}
	}

	function ask_before_nav() {
		if (props.cache?.dirty === true) {
			if (confirm("Go back without saving?")) {
				navigate(-1);
			} else {
				return;
			}
		} else {
			navigate(-1);
		}
	}

	function make_dirty() {
		if (!props.cache?.noteid)
			return;
		props.setCache('dirty', true);
	}

	function _update_note() {
		if (!props.cache?.noteid || props.cache.dirty!==true)
			return;
		props.request_update_note(dom_title.value, dom_content.value);
	}

	return (
		<>
			<div class="editor" classList={{hidden: props.is_hidden}}>
				<Show when={props.cache?.noteid==params.noteid} fallback={<Loader />}>
					<div class="editor-header">
						{/*<div ref={dom_title} class="title-input" contenteditable="true" onInput={make_dirty}>{props.cache.title}</div>*/}
						<input ref={dom_title} type="text"
							value={props.cache.title}
							onInput={make_dirty}
							class="title-input"
							placeholder="Note title...">
						</input>
					</div>

					<div class="editor-body">
						{/*<div ref={dom_content} class="content-textarea" contenteditable="true" onInput={make_dirty}>
							{props.cache.textcontent}
						</div>*/}
						<textarea ref={dom_content} onInput={make_dirty}
							value={props.cache.textcontent}
							class="content-textarea"
							placeholder="Write your note here...">
						</textarea>
					</div>

					<div class="editor-footer">
						<a class="toolbtn_lg" onClick={ask_before_nav}>
							<IoArrowUndoSharp class="text-gray-600" size="1.5rem" />
						</a>
						<a class="toolbtn_lg" onClick={_update_note} bool:disabled={!props.cache?.dirty}>
							<RiDeviceSave3Line class="text-gray-600" size="1.5rem" />
						</a>
						<a class="toolbtn_lg" onClick={ask_before_deletion}>
							<RiSystemDeleteBin5Line class="text-gray-600" size="1.5rem" />
						</a>
					</div>
				</Show>
			</div>
		</>
	);
}

export default NoteEditor;
