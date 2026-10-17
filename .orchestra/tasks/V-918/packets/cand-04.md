# Candidate cand-04

## ORIGIN commit adfb56dde0 (2026-06-12): simplify New Orchestrator modal — hide Profile/Pipeline/Role, sane defaults
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 17d456022..2897117d5 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -603,19 +603,19 @@ function autoNameFromPath(path) {
     const folder = parts[parts.length - 1] || '';
     return folder + '-orchestrator';
 }
 
 async function createOrchestrator() {
     const name = $('#orch-name').value.trim();
     const cwd = $('#orch-cwd').value.trim();
     const model = $('#orch-model').value;
-    const profile = $('#orch-profile').value;
-    const pipeline = $('#orch-pipeline').value;
-    const role = $('#orch-role').value;
+    const profile = $('#orch-profile').value || 'personal';
+    const pipeline = $('#orch-pipeline').value || 'default';
+    const role = $('#orch-role').value || 'orchestrator';
     const errEl = $('#orch-error');
     if (!name || !cwd) { errEl.textContent = 'Name and project path required'; errEl.classList.remove('hidden'); return; }
     const btn = $('#create-orch-btn');
     btn.disabled = true; btn.textContent = 'Creating...'; errEl.classList.add('hidden');
     try {
         await api('/api/sessions', { method: 'POST', body: JSON.stringify({ name, cwd, model, profile, pipeline, role, is_orchestrator: true }) });
         closeModal(); $('#orch-name').value = ''; $('#orch-cwd').value = '';
         currentScope = null;
diff --git a/app/templates/dashboard.html b/app/templates/dashboard.html
index d5039582d..bd5a7de73 100644
--- a/app/templates/dashboard.html
+++ b/app/templates/dashboard.html
@@ -78,31 +78,20 @@
                     </div>
                     <div id="project-picker" class="hidden mt-2 max-h-48 overflow-y-auto bg-slate-900 border border-slate-700 rounded-lg"></div>
                 </div>
                 <div>
                     <label class="text-xs text-slate-500 block mb-1">Model</label>
                     <select id="orch-model" class="w-full px-3 py-2 bg-slate-900 border border-slate-800 rounded-lg text-sm focus:border-indigo-500 focus:outline-none">
                     </select>
                 </div>
-                <div>
-                    <label class="text-xs text-slate-500 block mb-1">Profile</label>
-                    <select id="orch-profile" class="w-full px-3 py-2 bg-slate-900 border border-slate-800 rounded-lg text-sm focus:border-indigo-500 focus:outline-none">
-                    </select>
-                </div>
-                <div>
-                    <label class="text-xs text-slate-500 block mb-1">Pipeline</label>
-                    <select id="orch-pipeline" class="w-full px-3 py-2 bg-slate-900 border border-slate-800 rounded-lg text-sm focus:border-indigo-500 focus:outline-none">
-                    </select>
-                </div>
-                <div>
-                    <label class="text-xs text-slate-500 block mb-1">Role</label>
-                    <select id="orch-role" class="w-full px-3 py-2 bg-slate-900 border border-slate-800 rounded-lg text-sm focus:border-indigo-500 focus:outline-none">
-                    </select>
-                </div>
+                <!-- Profile/Pipeline/Role hidden — sane defaults for new orchestrators -->
+                <select id="orch-profile" class="hidden"></select>
+                <select id="orch-pipeline" class="hidden"></select>
+                <select id="orch-role" class="hidden"></select>
                 <div id="orch-error" class="text-xs text-red-400 hidden"></div>
                 <button id="create-orch-btn" class="w-full py-2 bg-indigo-600 hover:bg-indigo-500 rounded-lg text-sm font-medium transition-colors">Create Orchestrator</button>
             </div>
         </div>
     </div>
 
     <!-- Delete Orchestrator Modal -->
     <div id="delete-orch-modal" class="fixed inset-0 bg-black/60 backdrop-filter backdrop-blur-sm z-50 items-center justify-center hidden">


## LATER FIX b5b7890c1c (3.3 days later): fix: hardcode role=orchestrator for New Orchestrator — hidden dropdown was picking random role
lines of origin it changed/deleted: 3
(code only, capped 400 lines)

fix: hardcode role=orchestrator for New Orchestrator — hidden dropdown was picking random role


diff --git a/app/static/js/app.js b/app/static/js/app.js
index ec1848652..52e8beec9 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -629,19 +629,19 @@ function autoNameFromPath(path) {
     const folder = parts[parts.length - 1] || '';
     return folder + '-orchestrator';
 }
 
 async function createOrchestrator() {
     const name = $('#orch-name').value.trim();
     const cwd = $('#orch-cwd').value.trim();
     const model = $('#orch-model').value;
-    const profile = $('#orch-profile').value || 'personal';
-    const pipeline = $('#orch-pipeline').value || 'default';
-    const role = $('#orch-role').value || 'orchestrator';
+    const profile = 'personal';
+    const pipeline = 'default';
+    const role = 'orchestrator';
     const errEl = $('#orch-error');
     if (!name || !cwd) { errEl.textContent = 'Name and project path required'; errEl.classList.remove('hidden'); return; }
     const btn = $('#create-orch-btn');
     btn.disabled = true; btn.textContent = 'Creating...'; errEl.classList.add('hidden');
     try {
         await api('/api/sessions', { method: 'POST', body: JSON.stringify({ name, cwd, model, profile, pipeline, role, is_orchestrator: true }) });
         closeModal(); $('#orch-name').value = ''; $('#orch-cwd').value = '';
         currentScope = null;