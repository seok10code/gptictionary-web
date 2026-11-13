// The extension checks only completed Q/A structure. The server classifies intent.
globalThis.GPTIC_POLICY = (() => {
    const enabledKey = 'gptic:auto-enabled';
    function select(pairs) {
        return pairs.map(() => true);
    }
    return {enabledKey, select};
})();
