/// <reference types="vite/client" />

declare module '*.pdf' {
  const src: string
  export default src
}

declare module 'pdfjs-dist/build/pdf.worker.mjs?url' {
  const src: string
  export default src
}