import "./fonts.css"; // self-hosted Studio typefaces, inlined into the bundle
import { mount } from "svelte";
import App from "./App.svelte";

const app = mount(App, { target: document.getElementById("app") });

export default app;
