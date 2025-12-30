import { A, useNavigate, Navigate } from "@solidjs/router";

export function Main() {
  const navigate = useNavigate();

  let username = localStorage.getItem('lastusername');

  if (!username) {
    navigate("/login2");
  } else {
    navigate(`/${username}`);
  }

  return (
    <Navigate href="/login2" />
  );
}

export default Main;
