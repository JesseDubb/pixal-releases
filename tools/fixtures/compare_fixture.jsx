import React from "react";
import { createRoot } from "react-dom/client";
import { Chat } from "../../web/src/components/Chat.jsx";
import { api } from "../../web/src/store.js";

const fixture = await (await fetch("/fixture")).json();
createRoot(document.getElementById("app")).render(<Chat />);
await api.loadLane();
window.compareFixture = {
  index: () => api.lb?.idx,
  open: (index = 0) => api.setLb({ images: fixture.images, idx: index,
    meta: { scene: "Post-processing comparison — isolated browser test", template: "h3_ref_still" } }),
};
