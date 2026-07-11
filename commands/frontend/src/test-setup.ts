import '@testing-library/jest-dom'

// Ant Design 依赖 window.matchMedia，jsdom 默认没有
window.matchMedia = window.matchMedia || function matchMedia() {
  return {
    matches: false,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }
}

// 防止 getComputedStyle 在 Ant Design 某些版本中报错
const originalGetComputedStyle = window.getComputedStyle
window.getComputedStyle = (elt, pseudoElt) => {
  try {
    return pseudoElt ? originalGetComputedStyle(elt) : originalGetComputedStyle(elt, pseudoElt)
  } catch {
    return {} as CSSStyleDeclaration
  }
}

class TestResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver = globalThis.ResizeObserver || TestResizeObserver
