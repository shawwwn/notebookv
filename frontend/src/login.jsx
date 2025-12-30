import { useNavigate, useBeforeLeave } from "@solidjs/router";

export function Login(props) {
	const navigate = useNavigate();


	try {
		var user = JSON.parse(localStorage.getItem('user'));
		navigate(`/${user.username}`);

	} catch (error) {

	}

	var dom_form;
	var dom_username;
	var dom_password;

	function on_type(evt) {
		dom_username.classList.remove("wrong_password");
		dom_password.classList.remove("wrong_password");
	}

	function user_login(evt) {
		evt.preventDefault();

		var formData = new FormData(dom_form);
		var payload = Object.fromEntries(formData.entries());
		if (payload.username==="" || payload.password==="") {
			dom_username.value = "";
			dom_password.value = "";
			return;
		}

		fetch('/api/login', {
			method: 'POST',
			body: new URLSearchParams(payload)
		})
		.then(response => response.json())
		.then(data => {
			if (data.code === 200) {
				// success
				localStorage.setItem('user', JSON.stringify(data.content));
				navigate(`/${data.content.username}`);
			} else if (data.status === 'already logged in') {
				// TODO: redirect to logout previous user
				localStorage.setItem('user', JSON.stringify(data.content));
				navigate(`/${data.content.username}`);
			} else {
				throw("failed to login");
			}
		})
		.catch((error) => {
			dom_username.value = "";
			dom_password.value = "";
			dom_username.classList.add("wrong_password");
			dom_password.classList.add("wrong_password");
			console.error('Error:', error);
		});
	}


	return (
	<div class="flex flex-col items-center justify-center px-6 py-8 mx-auto md:h-screen lg:py-0 bg-gray-100">

		<a href="#" class="flex items-center mb-6 text-3xl font-semibold text-gray-900 dark:text-white">
			<img class="w-16 h-16 mr-2" src="/src/logo.svg" alt="logo" />
			Notebook<span class="text-blue-700 mx-1">V</span>
		</a>

		<div class="w-full max-w-md bg-white rounded-2xl shadow-lg p-8">

			<form ref={dom_form} method="POST" action="/api/login">
				<div class="mt-4">
					<label for="username" class="block text-sm font-medium text-gray-700 mb-1">
						Username
					</label>
					<input ref={dom_username} onFocus={on_type}
						id="username"
						name="username"
						type="text"
						placeholder=""
						class="w-full px-4 py-2 border rounded-lg"
					/>
				</div>

				<div class="mt-4">
					<label for="password" class="block text-sm font-medium text-gray-700 mb-1">
						Password
					</label>
					<input ref={dom_password} onFocus={on_type}
						id="password"
						name="password"
						type="password"
						placeholder=""
						class="w-full px-4 py-2 border rounded-lg"
						autocomplete="on"
					/>
				</div>

				<div class="mt-4 flex items-center justify-between text-sm">
					<label for="remember" class="flex items-center gap-2">
						<input id="remember" name="remember" type="checkbox" class="rounded border-gray-300 text-blue-600" />
						Remember me
					</label>
				</div>

				<button id="login_btn" onClick={user_login} class="mt-4 w-full bg-blue-600 hover:bg-blue-700 text-white py-2 rounded-lg font-semibold transition" type="submit">Sign In</button>
			</form>
		</div>

	</div>
	);
}

export default Login;
