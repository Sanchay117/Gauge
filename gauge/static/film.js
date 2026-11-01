// The landing page's time slice: each x position is one frame of the film.
(async () => {
  const get = (id) => document.getElementById(id);
  const plate = get("plate"), slice = get("slice"), video = get("film-video"), range = get("film-range");
  const REST_FRAME = 106;
  const { fps, heights } = await fetch("/slice.json").then((res) => res.json());
  const last = heights.length - 1;

  function show(frame) {
    const rect = slice.getBoundingClientRect(), box = plate.getBoundingClientRect();
    const x = rect.left - box.left + (frame / last) * rect.width;
    get("cursor").hidden = get("finder").hidden = false;
    get("cursor").style.left = `${x}px`;
    const finder = get("finder");
    // Sit on the far side of the cursor so the viewfinder never hides the arc under it.
    const side = x > box.width / 2 ? x - finder.offsetWidth - 16 : x + 16;
    finder.style.left = `${Math.min(Math.max(side, 8), box.width - finder.offsetWidth - 8)}px`;
    video.currentTime = frame / fps + 0.001;
    const height = heights[frame];
    get("finder-read").textContent = `${(frame / fps).toFixed(2)} s  ${height > 0 ? `${height.toFixed(2)} m up` : "on the ground"}`;
    range.value = frame;
  }

  plate.addEventListener("pointermove", (event) => {
    const rect = slice.getBoundingClientRect();
    const share = (event.clientX - rect.left) / rect.width;
    show(Math.round(Math.min(Math.max(share, 0), 1) * last));
  });
  range.addEventListener("input", () => show(Number(range.value)));
  window.addEventListener("resize", () => show(Number(range.value)));

  get("axis").textContent = `${(last / fps).toFixed(0)} seconds of film`;
  get("sample-again").onclick = () => get("sample").click();

  // One sweep on arrival shows that the image is the film, then it rests on the first jump's peak.
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (calm) return show(REST_FRAME);
  let started = null, touched = false;
  plate.addEventListener("pointerenter", () => { touched = true; }, { once: true });
  const sweep = (now) => {
    if (touched) return;
    started ??= now;
    const done = Math.min((now - started) / 2600, 1);
    const eased = 1 - (1 - done) ** 3;
    show(Math.round(eased * REST_FRAME));
    if (done < 1) requestAnimationFrame(sweep);
  };
  requestAnimationFrame(sweep);
})();
