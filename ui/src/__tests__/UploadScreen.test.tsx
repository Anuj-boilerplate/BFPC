import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ApiError, indexDocument } from '../api/client'
import type { IndexResponse } from '../api/types'
import UploadScreen from '../screens/UploadScreen'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, indexDocument: vi.fn() }
})

const mockedIndex = vi.mocked(indexDocument)

const pdfFile = () => new File(['%PDF-1.4 fake bytes'], 'report.pdf', { type: 'application/pdf' })

const indexResponse: IndexResponse = {
  filename: 'report.pdf',
  source: 'pdf',
  pages: 20,
  chunks: 97,
  kinds: { text: 63, table: 18, heading: 14, list: 2 },
}

function renderUpload(onIndexed = vi.fn(), onToast = vi.fn()) {
  const utils = render(<UploadScreen onIndexed={onIndexed} onToast={onToast} />)
  const input = utils.container.querySelector('input[type="file"]') as HTMLInputElement
  return { onIndexed, onToast, input, ...utils }
}

describe('UploadScreen', () => {
  beforeEach(() => {
    mockedIndex.mockReset()
  })

  it('indexes a PDF chosen via the file input', async () => {
    mockedIndex.mockResolvedValue(indexResponse)
    const { onIndexed, onToast, input } = renderUpload()
    await userEvent.setup().upload(input, pdfFile())

    await waitFor(() => expect(onIndexed).toHaveBeenCalledTimes(1))
    expect(mockedIndex).toHaveBeenCalledWith(expect.objectContaining({ name: 'report.pdf' }))
    expect(onIndexed).toHaveBeenCalledWith(indexResponse)
    expect(onToast).not.toHaveBeenCalled()
  })

  it('indexes a file dropped onto the dropzone', async () => {
    mockedIndex.mockResolvedValue(indexResponse)
    const { onIndexed, onToast } = renderUpload()
    const dropzone = screen.getByRole('button', { name: 'Upload a PDF document' })
    fireEvent.drop(dropzone, { dataTransfer: { files: [pdfFile()] } })

    await waitFor(() => expect(onIndexed).toHaveBeenCalledTimes(1))
    expect(onToast).not.toHaveBeenCalled()
  })

  it('rejects non-PDF files without calling the API', async () => {
    const { onIndexed, onToast, input } = renderUpload()
    fireEvent.change(input, { target: { files: [new File(['# hi'], 'notes.md', { type: 'text/markdown' })] } })

    expect(onToast).toHaveBeenCalledWith('Only PDF files are supported in the UI.')
    expect(mockedIndex).not.toHaveBeenCalled()
    expect(onIndexed).not.toHaveBeenCalled()
  })

  it('surfaces server errors as toasts', async () => {
    mockedIndex.mockRejectedValue(new ApiError(500, 'Embedding model failed to load'))
    const { onIndexed, onToast, input } = renderUpload()
    await userEvent.setup().upload(input, pdfFile())

    await waitFor(() => expect(onToast).toHaveBeenCalledWith('Embedding model failed to load'))
    expect(onIndexed).not.toHaveBeenCalled()
  })

  it('shows a busy state while indexing is in flight', async () => {
    let resolveIndex!: (response: IndexResponse) => void
    mockedIndex.mockImplementation(() => new Promise((resolve) => { resolveIndex = resolve }))
    const { input } = renderUpload()
    await userEvent.setup().upload(input, pdfFile())

    expect(screen.getByText('Indexing document…')).toBeInTheDocument()

    resolveIndex(indexResponse)
    await waitFor(() => expect(screen.queryByText('Indexing document…')).not.toBeInTheDocument())
  })
})
