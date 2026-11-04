if (window.location.pathname.replace(/\/$/, "") === "/review") {
  import("./reviewer.jsx");
} else {
  import("./main.jsx");
}
