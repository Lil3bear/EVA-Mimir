export function createTranslationClient({ native = () => globalThis.Translator, request }) {
  const cache = new Map();
  let translator;
  return async ({ text, engine, model, onProgress = () => {} }) => {
    const key = JSON.stringify([engine, model, text]);
    if (cache.has(key)) return cache.get(key);
    const pending = (async () => {
      if (engine !== "browser") return (await request(engine, text)).translation;
      const api = native();
      if (!api) throw new Error("当前浏览器不支持本地翻译。可用桌面 Chrome 打开，或手动选择快速云翻译；不会自动调用论文模型。");
      const started = Date.now();
      const heartbeat = setInterval(
        () => onProgress(`正在准备本地语言包…已等待 ${Math.round((Date.now() - started) / 1000)}s`),
        5000,
      );
      let timeout;
      try {
        if (typeof api.availability === "function") {
          const availability = await Promise.race([
            api.availability({sourceLanguage: "en", targetLanguage: "zh"}).catch(() => null),
            new Promise(resolve => setTimeout(() => resolve("timeout"), 3000)),
          ]);
          if (availability === "timeout") onProgress("浏览器没有及时返回语言包状态，直接尝试准备");
          if (availability === "unavailable")
            throw new Error("当前浏览器没有英语→简体中文语言包，也无法下载。请在桌面 Chrome 的 chrome://on-device-translation-internals 检查后重试，或改用快速云翻译。");
          if (availability === "downloadable") onProgress("需要首次下载英语→简体中文语言包（几十 MB，由 Chrome 提供）");
          if (availability === "downloading") onProgress("Chrome 正在下载语言包");
        } else {
          onProgress("正在检查本地语言包");
        }
        translator ||= api.create({
          sourceLanguage: "en",
          targetLanguage: "zh",
          monitor(m) {
            const report = event => onProgress(`语言包下载 ${Math.round((event.loaded || 0) * 100)}%`);
            if (typeof m.addEventListener === "function") m.addEventListener("downloadprogress", report);
            else m.onprogress = report;
          },
        }).catch(error => {
          translator = null;
          throw new Error(`本地语言包准备失败：${error?.message || "浏览器未完成下载"}。可在桌面 Chrome 重试，或选择快速云翻译。`);
        });
        const timeoutError = new Promise((_, reject) => {
          timeout = setTimeout(() => {
            translator = null;
            reject(new Error("本地语言包准备超时（90 秒）。可打开 chrome://on-device-translation-internals 检查/安装英语→简体中文语言包，或改用快速云翻译。"));
          }, 90000);
        });
        const ready = await Promise.race([translator, timeoutError]);
        onProgress("正在本地翻译");
        return await ready.translate(text);
      } finally {
        clearInterval(heartbeat);
        if (timeout) clearTimeout(timeout);
      }
    })();
    cache.set(key, pending);
    try {
      const value = await pending;
      if (cache.size > 500) cache.delete(cache.keys().next().value);
      return value;
    } catch (error) {cache.delete(key); throw error;}
  };
}
