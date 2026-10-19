export function createTranslationClient({ native = () => globalThis.Translator, request }) {
  const cache = new Map();
  let translator;
  return async ({ text, engine, model, onProgress = () => {} }) => {
    const key = JSON.stringify([engine,model,text]);
    if (cache.has(key)) return cache.get(key);
    const pending = (async () => {
      if (engine !== "browser") return (await request(engine,text)).translation;
      const api = native();
      if (!api) throw new Error("当前浏览器不支持本地翻译。可用桌面 Chrome 打开，或手动选择快速云翻译；不会自动调用论文模型。");
      onProgress("正在准备本地语言包");
      translator ||= api.create({sourceLanguage:"en",targetLanguage:"zh",monitor(m) {
        m.addEventListener("downloadprogress",e => onProgress(`语言包下载 ${Math.round(e.loaded*100)}%`));
      }}).catch(() => {translator = null; throw new Error("本地语言包暂不可用。可在桌面 Chrome 重试，或手动选择快速云翻译；不会自动使用论文模型额度。");});
      const ready = await translator;
      onProgress("正在本地翻译");
      return ready.translate(text);
    })();
    cache.set(key,pending);
    try {
      const value = await pending;
      if (cache.size > 500) cache.delete(cache.keys().next().value);
      return value;
    } catch (error) {cache.delete(key); throw error;}
  };
}
