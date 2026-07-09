import Reports from "../Reports"
describe("Reports page", () => {
  it("can be imported", () => {
    expect(Reports).toBeDefined()
    expect(typeof Reports).toBe("function")
  })
})