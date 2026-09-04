const mockSetParams = jest.fn()
let mockParams = new URLSearchParams()

export const useSearchParams = () => [mockParams, mockSetParams]

export const __setMockSearchParams = (params) => {
  mockParams = params
}

export const __getMockSetParams = () => mockSetParams
