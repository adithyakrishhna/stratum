/**
 * API client utilities — intentionally contains security vulnerabilities
 * and code quality issues to test Stratum PR review detection.
 *
 * Expected Stratum findings when this file is in a PR
 * ----------------------------------------------------
 * Security:
 *   CRITICAL  Hardcoded API key              line  24
 *   CRITICAL  Hardcoded auth token           line  25
 *   CRITICAL  eval() usage                   parseServerResponse
 *   MEDIUM    Math.random() for token        generateRequestId
 *   MEDIUM    Direct innerHTML assignment    renderUserContent
 *   MEDIUM    Direct innerHTML assignment    updateDashboardWidget
 *
 * Rules (default thresholds — no stratum.yaml needed):
 *   MEDIUM    MAX_FUNCTION_LINES    fetchAndProcessUserData  (~60 lines > 50)
 *   HIGH      MAX_COMPLEXITY        fetchAndProcessUserData  (complexity ~22 > 10)
 *
 * DO NOT DEPLOY — testing file only.
 */


// ── Hardcoded credentials ─────────────────────────────────────────────
// Triggers: HARDCODED_SECRET (critical) for both lines
const API_KEY = "apikey_live_xK9mP2nR4qT7wY1vZ3uA8bC6dEfG";
const AUTH_TOKEN = "auth_token_prod_9mXpL2kQ4wR7yN1vB3sE6hC8";


// ── eval() on server response ─────────────────────────────────────────
// Triggers: DANGEROUS_FUNCTION eval() (critical)
function parseServerResponse(responseText) {
    return eval(responseText);
}


// ── Insecure Math.random() for request ID ─────────────────────────────
// Triggers: INSECURE_RANDOM (medium) — use crypto.randomUUID() instead
function generateRequestId() {
    return "req_" + Math.random().toString(36).substr(2, 9);
}


// ── Direct innerHTML assignment ────────────────────────────────────────
// Triggers: DANGEROUS_FUNCTION innerHTML= (medium) × 2 across two functions
function renderUserContent(containerId, htmlContent) {
    const el = document.getElementById(containerId);
    if (el) {
        el.innerHTML = htmlContent;
    }
}


function updateDashboardWidget(widgetId, serverData) {
    const widget = document.querySelector(`#${widgetId}`);
    if (widget) {
        widget.innerHTML = serverData.html;
    }
}


// ── Long + highly complex function ────────────────────────────────────
// Triggers:
//   MAX_FUNCTION_LINES  (medium) — ~60 lines > 50
//   MAX_COMPLEXITY      (high)   — complexity ~21 > 10
async function fetchAndProcessUserData(userId, options, retryCount = 0) {
    /**
     * Fetch user data from the API with validation, retries, and
     * multi-step post-processing. Intentionally long and complex
     * to test MAX_FUNCTION_LINES and MAX_COMPLEXITY rules.
     */
    if (!userId) {
        return { success: false, error: "userId is required" };
    }

    if (typeof userId !== "string" && typeof userId !== "number") {
        return { success: false, error: "userId must be a string or number" };
    }

    if (retryCount > 3) {
        return { success: false, error: "Max retries exceeded" };
    }

    const requestId = generateRequestId();
    const headers = {
        "Authorization": `Bearer ${AUTH_TOKEN}`,
        "X-API-Key": API_KEY,
        "X-Request-Id": requestId,
        "Content-Type": "application/json",
    };

    let response;
    try {
        response = await fetch(`/api/v2/users/${userId}`, {
            method: "GET",
            headers,
        });
    } catch (networkErr) {
        if (retryCount < 3) {
            await new Promise(r => setTimeout(r, 1000 * (retryCount + 1)));
            return fetchAndProcessUserData(userId, options, retryCount + 1);
        }
        return { success: false, error: "Network error: " + networkErr.message };
    }

    if (response.status === 401) {
        return { success: false, error: "Unauthorized — check credentials" };
    }

    if (response.status === 403) {
        return { success: false, error: "Forbidden — insufficient permissions" };
    }

    if (response.status === 404) {
        return { success: false, error: "User not found" };
    }

    if (!response.ok) {
        return { success: false, error: `API error ${response.status}` };
    }

    let data;
    try {
        data = await response.json();
    } catch {
        return { success: false, error: "Failed to parse API response" };
    }

    if (!data || !data.user) {
        return { success: false, error: "Invalid response structure" };
    }

    const user = data.user;

    if (options && options.enrichProfile) {
        if (user.avatar_url) {
            renderUserContent("avatar-container", `<img src="${user.avatar_url}">`);
        }
        if (user.bio_html) {
            updateDashboardWidget("bio-widget", { html: user.bio_html });
        }
    }

    if (options && options.validatePermissions) {
        const perms = user.permissions || [];
        if (!perms.includes("active")) {
            return { success: false, error: "User account is not active" };
        }
        if (options.requireAdmin && !perms.includes("admin")) {
            return { success: false, error: "Admin permission required" };
        }
    }

    return {
        success: true,
        user,
        requestId,
        fetchedAt: Date.now(),
    };
}


// ── Exports ────────────────────────────────────────────────────────────
export {
    parseServerResponse,
    generateRequestId,
    renderUserContent,
    updateDashboardWidget,
    fetchAndProcessUserData,
};
