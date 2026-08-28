function MobileTouch(eventBus, canvas) {
  const el = canvas.getContainer();

  let isPanning = false;
  let isPinching = false;

  let startPt = null;
  let lastPt = null;

  let startZoom = 1;
  let startDist = 0;
  let lastCenter = null;

  const PAN_THRESHOLD = 8; // px

  function dist(a, b) {
    const dx = b.clientX - a.clientX, dy = b.clientY - a.clientY;
    return Math.hypot(dx, dy);
  }

  function center(a, b) {
    return { x: (a.clientX + b.clientX) / 2, y: (a.clientY + b.clientY) / 2 };
  }

  function pt(t) {
    return { x: t.clientX, y: t.clientY };
  }

  function movedEnough(p1, p2) {
    if (!p1 || !p2) return false;
    const dx = p2.x - p1.x;
    const dy = p2.y - p1.y;
    return (dx * dx + dy * dy) >= (PAN_THRESHOLD * PAN_THRESHOLD);
  }

  function onStart(e) {
    if (e.touches.length === 2) {
      isPinching = true;
      isPanning = false;

      // for pinch, we must prevent browser zoom/scroll
      e.preventDefault();

      const [t0, t1] = e.touches;
      startDist = dist(t0, t1) || 1;
      startZoom = canvas.zoom() || 1;
      lastCenter = center(t0, t1);
      startPt = null;
      lastPt = null;
      return;
    }

    if (e.touches.length === 1 && !isPinching) {
      // IMPORTANT: do NOT preventDefault here (preserve tap)
      startPt = pt(e.touches[0]);
      lastPt = startPt;
      isPanning = false; // arm panning, but don’t start it yet
    }
  }

  function onMove(e) {
    if (isPinching && e.touches.length === 2) {
      e.preventDefault();

      const [t0, t1] = e.touches;
      const c = center(t0, t1);
      const scale = dist(t0, t1) / (startDist || 1);

      canvas.zoom(startZoom * scale, c);

      // keep center stable
      canvas.scroll({ dx: (c.x - lastCenter.x), dy: (c.y - lastCenter.y) });
      lastCenter = c;
      return;
    }

    if (!isPinching && e.touches.length === 1) {
      const p = pt(e.touches[0]);

      // start panning only after threshold exceeded
      if (!isPanning) {
        if (!movedEnough(startPt, p)) {
          // still considered a tap: DO NOT preventDefault
          lastPt = p;
          return;
        }
        isPanning = true;
      }

      // now we are panning -> prevent default and scroll canvas
      e.preventDefault();
      canvas.scroll({ dx: (p.x - lastPt.x), dy: (p.y - lastPt.y) });
      lastPt = p;
    }
  }

  function onEnd(e) {
    if (e.touches.length < 2) isPinching = false;
    if (e.touches.length === 0) isPanning = false;
    if (e.touches.length === 0) {
      startPt = null;
      lastPt = null;
      lastCenter = null;
      startDist = 0;
    }
  }

  // Allow preventDefault() in move/pinch
  el.addEventListener("touchstart", onStart, { passive: false });
  el.addEventListener("touchmove", onMove, { passive: false });
  el.addEventListener("touchend", onEnd, { passive: false });
  el.addEventListener("touchcancel", onEnd, { passive: false });

  // Keep browser from doing native gestures when we do pan/pinch
  // (we’re careful not to cancel taps ourselves)
  el.style.touchAction = "manipulation"; // better for allowing tap
  // If you still see page scroll during pan, switch back to "none":
  // el.style.touchAction = "none";
}

MobileTouch.$inject = ["eventBus", "canvas"];

window.MobileTouchModule = function() {
  return {
    __init__: ["mobileTouch"],
    mobileTouch: ["type", MobileTouch],
  };
};
