/* DocuExtract shared helpers (window.DX) */
(function () {
    "use strict";

    const DX = (window.DX = {});

    DX.$ = (selector, root = document) => root.querySelector(selector);
    DX.$$ = (selector, root = document) => [...root.querySelectorAll(selector)];

    DX.esc = value =>
        String(value ?? "").replace(/[&<>"']/g, ch => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
        }[ch]));

    DX.fmtSize = bytes => {
        if (bytes < 1024) return bytes + " B";
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + " KB";
        return (bytes / 1024 / 1024).toFixed(1) + " MB";
    };

    DX.plural = (n, one, many) => `${n} ${n === 1 ? one : many || one + "s"}`;

    DX.timeAgo = ts => {
        const s = Math.round((Date.now() - ts) / 1000);
        if (s < 45) return "just now";
        if (s < 3600) return Math.round(s / 60) + " min ago";
        if (s < 86400) return Math.round(s / 3600) + " h ago";
        return new Date(ts).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
    };

    /* small inline icons for markup built in JS */
    const SVG = {
        file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>',
        check: '<polyline points="20 6 9 17 4 12"/>',
        x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
        alert: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
        info: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
        scan: '<path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2"/><line x1="7" y1="12" x2="17" y2="12"/>',
        download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
        upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
        table: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18"/>',
    };
    DX.svg = (name, size = 18) =>
        `<svg class="icon" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${SVG[name] || ""}</svg>`;

    /* ---------- toasts ---------- */
    DX.toast = (message, type = "info", ms = 4200) => {
        const box = document.getElementById("toasts");
        if (!box) return;
        const el = document.createElement("div");
        el.className = "toast " + type;
        el.textContent = message;
        box.appendChild(el);
        setTimeout(() => el.remove(), ms);
    };

    /* ---------- clipboard ---------- */
    DX.copy = async text => {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (_) {
            const area = document.createElement("textarea");
            area.value = text;
            area.style.cssText = "position:fixed;opacity:0";
            document.body.appendChild(area);
            area.select();
            let ok = false;
            try { ok = document.execCommand("copy"); } catch (_) { /* ignore */ }
            area.remove();
            return ok;
        }
    };

    /* ---------- downloads ---------- */
    DX.save = (blob, name) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = name;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 2000);
    };

    function filenameFrom(disposition) {
        if (!disposition) return null;
        const star = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
        if (star) { try { return decodeURIComponent(star[1]); } catch (_) { /* fall through */ } }
        const plain = /filename="?([^";]+)"?/i.exec(disposition);
        return plain ? plain[1] : null;
    }

    /* ---------- requests (XHR so uploads can report progress) ---------- */
    DX.request = (url, opts = {}) =>
        new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open(opts.method || "POST", url);
            xhr.responseType = "blob";

            let body = opts.body || null;
            if (opts.json !== undefined) {
                xhr.setRequestHeader("Content-Type", "application/json");
                body = JSON.stringify(opts.json);
            }

            if (xhr.upload) {
                if (opts.onUpload) {
                    xhr.upload.onprogress = e => e.lengthComputable && opts.onUpload(e.loaded / e.total);
                }
                if (opts.onUploadDone) xhr.upload.onload = opts.onUploadDone;
            }

            xhr.onerror = () => {
                const err = new Error("Couldn't reach the server. Check your connection and that the app is running.");
                err.code = "network";
                reject(err);
            };

            xhr.onload = async () => {
                const blob = xhr.response;
                if (xhr.status >= 200 && xhr.status < 300) {
                    resolve({
                        blob,
                        filename: filenameFrom(xhr.getResponseHeader("Content-Disposition")),
                        header: name => xhr.getResponseHeader(name),
                    });
                    return;
                }
                let info = {};
                try { info = JSON.parse(await blob.text()); } catch (_) { /* not JSON */ }
                const err = new Error(info.error || `Request failed (${xhr.status}).`);
                err.code = info.code;
                err.status = xhr.status;
                err.filename = info.filename;
                reject(err);
            };

            xhr.send(body);
        });

    DX.json = async (url, opts) => JSON.parse(await (await DX.request(url, opts)).blob.text());

    /* ---------- recent conversions (stored only in this browser) ---------- */
    const HISTORY_KEY = "docuextract.recent.v1";

    DX.history = {
        get() {
            try { return JSON.parse(localStorage.getItem(HISTORY_KEY)) || []; } catch (_) { return []; }
        },
        add(entry) {
            try {
                const list = this.get();
                list.unshift({ ts: Date.now(), ...entry });
                localStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(0, 50)));
            } catch (_) { /* storage may be unavailable (private mode) */ }
        },
        clear() {
            try { localStorage.removeItem(HISTORY_KEY); } catch (_) { /* ignore */ }
        },
    };

    /* ---------- drag & drop ---------- */
    DX.dropzone = (zone, input, onFiles) => {
        input.addEventListener("change", () => {
            if (input.files.length) onFiles([...input.files]);
            input.value = "";
        });
        ["dragenter", "dragover"].forEach(type =>
            zone.addEventListener(type, e => { e.preventDefault(); zone.classList.add("dragging"); }));
        zone.addEventListener("dragleave", e => {
            if (!zone.contains(e.relatedTarget)) zone.classList.remove("dragging");
        });
        zone.addEventListener("drop", e => {
            e.preventDefault();
            zone.classList.remove("dragging");
            const files = [...e.dataTransfer.files];
            if (files.length) onFiles(files);
        });
    };

    // A PDF dropped outside a drop zone should not navigate away from the app.
    window.addEventListener("dragover", e => { if (!e.target.closest || !e.target.closest(".drop")) e.preventDefault(); });
    window.addEventListener("drop", e => { if (!e.target.closest || !e.target.closest(".drop")) e.preventDefault(); });

    /* ---------- mobile sidebar ---------- */
    document.addEventListener("DOMContentLoaded", () => {
        const sidebar = document.getElementById("sidebar");
        const scrim = document.getElementById("scrim");
        const button = document.getElementById("menuBtn");
        if (!sidebar || !button) return;

        const set = open => {
            sidebar.classList.toggle("open", open);
            scrim.classList.toggle("show", open);
            button.setAttribute("aria-expanded", String(open));
        };
        button.addEventListener("click", () => set(!sidebar.classList.contains("open")));
        scrim.addEventListener("click", () => set(false));
        document.addEventListener("keydown", e => { if (e.key === "Escape") set(false); });
    });
})();