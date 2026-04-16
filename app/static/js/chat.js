const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const chatLog = document.getElementById("chat-log");
const cuaLog = document.getElementById("cua-log");
const chatSubmit = document.getElementById("chat-submit");
const promptButtons = document.querySelectorAll("[data-prompt]");

function appendLog(kind, text) {
    if (!chatLog) return;
    const row = document.createElement("div");
    row.className = `chat-row ${kind}`;
    row.textContent = text;
    chatLog.appendChild(row);
}

function appendCua(text) {
    if (!cuaLog) return;
    const row = document.createElement("div");
    row.className = "chat-row cua";
    row.textContent = text;
    cuaLog.appendChild(row);
}

promptButtons.forEach((button) => {
    button.addEventListener("click", () => {
        chatInput.value = button.dataset.prompt || "";
        chatInput.focus();
    });
});

if (chatForm) {
    chatForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const message = chatInput.value.trim();
        if (!message) {
            showToast("Please enter a request.", "error");
            return;
        }
        try {
            if (chatSubmit) {
                chatSubmit.disabled = true;
                chatSubmit.textContent = "Running...";
            }
            chatLog.innerHTML = "";
            if (cuaLog) cuaLog.innerHTML = "";
            appendLog("user", `> ${message}`);
            appendLog("assistant", "Planning workflow...");

            const role = new URLSearchParams(window.location.search).get("role") || "IT_SUPPORT";
            const response = await fetch(`/api/chat/execute?role=${encodeURIComponent(role)}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message }),
            });

            const result = await response.json();
            chatLog.innerHTML = "";
            if (cuaLog) cuaLog.innerHTML = "";
            appendLog("assistant", result.summary || "No summary returned.");
            let cuaCount = 0;
            (result.logs || []).forEach((line) => {
                if (line.startsWith("[CUA]")) {
                    appendCua(line.replace("[CUA]", "").trim());
                    cuaCount += 1;
                } else {
                    appendLog("log", line);
                }
            });
            if (cuaCount === 0) {
                appendCua("No CUA decision needed for this run.");
            }

            if (response.ok) {
                showToast("Workflow finished.");
            } else {
                showToast(result.summary || "Workflow failed.", "error");
            }
        } catch (error) {
            showToast("Unable to execute workflow.", "error");
        } finally {
            if (chatSubmit) {
                chatSubmit.disabled = false;
                chatSubmit.textContent = "Run in browser";
            }
        }
    });
}

