import { useParams, useSearchParams, useNavigate, useBeforeLeave, useLocation } from "@solidjs/router";

import { Loader } from "/src/loader";



export function DashboardPage(props) {
	const navigate = useNavigate();
	const params = useParams();


	function relogin() {
		localStorage.removeItem("user");
		navigate('/login');
	}

	try {
		var user = JSON.parse(localStorage.getItem('user'));
		if (user.username === params.username) {

		} else {
			throw "username unmatched"
		}
	} catch (error) {

		relogin();
	}

	function get_user_notebooks() {
		return fetch(`/api/${params.username}/get`)
			.then(response => response.json())
			.then(data => {
				if (data.code === 200 && data.content?.notebooks.length>0) {
					return data.content;
				} else if (data.status === "login required") {
					console.error('user unauthenticated, redirect to login')
					relogin();
					return null;
				} else {
					throw("failed to get user notebooks");
				}
			})
			.catch((error) => {
				console.error('Error:', error);
				return null;
			});
	}

	// TODO: display a dashboard containing all notebooks
	get_user_notebooks().then(content=>{

		if (!content) {
			relogin();
			return;
		}

		// redirect to first notebook in collections
		var notebookid = content.notebooks[0].notebookid;
		navigate(`/note/${notebookid}`);

	}).catch(err=> {
		console.error(err);
	});


	return (
	<div>
		<Loader />
	</div>
	);
}

export default DashboardPage;
