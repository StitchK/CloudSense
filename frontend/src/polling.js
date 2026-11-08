// One batch at a time. Cleanup also ignores late results from non-abortable mocks.
export function startPolling({ load, onResult, onError, interval, canPoll = () => true }) {
  const controller = new AbortController();
  let timer;
  async function run(initial = false) {
    if (controller.signal.aborted) return;
    try {
      if (initial || canPoll()) {
        const result = await load(controller.signal);
        if (!controller.signal.aborted) onResult(result);
      }
    } catch (error) {
      if (!controller.signal.aborted) onError(error);
    } finally {
      if (!controller.signal.aborted) timer = setTimeout(run, interval);
    }
  }
  run(true);
  return () => {
    controller.abort();
    clearTimeout(timer);
  };
}
