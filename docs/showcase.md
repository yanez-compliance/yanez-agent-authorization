---
title: Showcase
description: Apps that Yanez developers built on the YID registry, from Pulse agents to partner integrations.
---

# Showcase

Apps built on the YID registry: agents that ask a human for approval through **Yanez Pulse**, and
partner apps that verify people with YID.

## Agents on Pulse

<ul class="showcase">
  <li>
    <a href="https://agent-auth-dev.yanezcompliance.com/" target="_blank" rel="noopener"><img src="{{ '/assets/showcase/yanez-mart.png' | relative_url }}" width="196" height="48" alt="Yanez Mart"></a>
    <span class="showcase-label">Ask the Agent what you want to buy</span>
  </li>
  <li>
    <a href="https://0xhound.com/" target="_blank" rel="noopener"><img src="{{ '/assets/showcase/yid-wallet.png' | relative_url }}" width="196" height="48" alt="YID Wallet"></a>
    <span class="showcase-label">Let your agent spend. <span class="showcase-grad">Never hand it your keys.</span></span>
  </li>
  <li>
    <a href="{{ '/assets/showcase/itkan-purchase-story.mp4' | relative_url }}" data-popup="video"><img src="{{ '/assets/showcase/itkan.png' | relative_url }}" width="196" height="48" alt="Itkan: play the purchase story video"></a>
    <span class="showcase-label">Biometric approval for a robotics purchase <a class="showcase-more" href="{{ '/assets/showcase/itkan-dashboard.png' | relative_url }}" data-popup="image">Dashboard</a></span>
  </li>
</ul>

## Partner apps on YID

<ul class="showcase">
  <li>
    <a href="https://www.dfusion.ai/" target="_blank" rel="noopener"><img src="{{ '/assets/showcase/dfusion.png' | relative_url }}" width="196" height="48" alt="dFusion AI"></a>
    <span class="showcase-label">Source and synthesize data into high-performance AI assets</span>
  </li>
  <li>
    <a href="https://syklo.io/en/" target="_blank" rel="noopener"><img src="{{ '/assets/showcase/syklo.png' | relative_url }}" width="196" height="48" alt="Syklo"></a>
    <span class="showcase-label">Dollars within reach for everyone</span>
  </li>
  <li>
    <a href="https://biovault-dev.yanezcompliance.com/" target="_blank" rel="noopener"><img src="{{ '/assets/showcase/biovault.png' | relative_url }}" width="196" height="48" alt="BioVault"></a>
    <span class="showcase-label">Your face is your key</span>
  </li>
</ul>

<dialog class="showcase-popup" id="showcase-popup" aria-label="Showcase media">
  <button type="button" class="showcase-close" aria-label="Close">&times;</button>
  <div></div>
</dialog>

<script>
(function () {
  var dlg = document.getElementById('showcase-popup');
  var box = dlg.querySelector('div');
  document.querySelectorAll('[data-popup]').forEach(function (link) {
    link.addEventListener('click', function (e) {
      e.preventDefault();
      var video = link.dataset.popup === 'video';
      var el = document.createElement(video ? 'video' : 'img');
      el.src = link.href;
      if (video) { el.controls = true; el.autoplay = true; el.playsInline = true; }
      else { el.alt = 'Itkan dashboard'; }
      box.replaceChildren(el);
      dlg.showModal();
      dlg.scrollTop = 0; // focusing the sticky close button scrolls the popup down otherwise
    });
  });
  // click on the backdrop or the close button closes; clearing the box stops the video
  dlg.addEventListener('click', function (e) { if (e.target === dlg) dlg.close(); });
  dlg.querySelector('.showcase-close').addEventListener('click', function () { dlg.close(); });
  dlg.addEventListener('close', function () { box.replaceChildren(); });
})();
</script>

## Add your agent

Built something with Pulse? Add an image to `docs/assets/showcase/` and a row to
[`docs/showcase.md`]({{ site.github_repo }}/blob/main/docs/showcase.md), then open a pull request.
