import PaperDashboard from "../PaperDashboard"
describe("PaperDashboard page", () => {
  it("can be imported", () => {
    expect(PaperDashboard).toBeDefined()
    expect(typeof PaperDashboard).toBe("function")
  })
})