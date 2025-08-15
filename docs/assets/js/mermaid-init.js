/* Mermaid initialisation for MkDocs Material */
(function(){
  function initMermaid(){
    if (!window.mermaid) return;
    try {
      window.mermaid.initialize({ startOnLoad: true, theme: 'default' });
      // Re-run on MkDocs Material page changes (if instant navigation is used)
      if (window.document$ && typeof window.document$.subscribe === 'function') {
        window.document$.subscribe(function(){
          try { window.mermaid.init(); } catch (e) { /* ignore */ }
        });
      }
    } catch (e) {
      console.error('Mermaid init failed', e);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initMermaid);
  } else {
    initMermaid();
  }
})();


