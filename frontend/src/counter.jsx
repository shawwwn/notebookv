import { createSignal } from "solid-js";

function Counter() {
  const [count, setCount] = createSignal(0); 
  const doubleCount = () => count() * 2; 
  return (
    <>
      <h1>Solid Counter</h1>
      <p>Current count: {count()}</p>
      <p>Double count: {doubleCount()}</p>
      <button onClick={() => setCount(c => c + 1)}>Increment</button>
      <button onClick={() => setCount(c => c - 1)}>Decrement</button>
    </>
  );
}

export default Counter;
