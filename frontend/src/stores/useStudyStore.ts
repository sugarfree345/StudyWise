import { create } from 'zustand'

/** 学习页全局状态：当前页码是左右两个窗格同步的唯一依据。 */
interface StudyState {
  currentPage: number
  pageCount: number
  setPageCount: (count: number) => void
  goToPage: (page: number) => void
}

export const useStudyStore = create<StudyState>((set) => ({
  currentPage: 1,
  pageCount: 1,
  setPageCount: (count) => set({ pageCount: count, currentPage: 1 }),
  goToPage: (page) =>
    set((state) => ({
      currentPage: Math.min(Math.max(1, page), state.pageCount),
    })),
}))
