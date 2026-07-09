import AgentConsole from "../AgentConsole"
describe("AgentConsole page", () => {
  it("can be imported", () => {
    expect(AgentConsole).toBeDefined()
    expect(typeof AgentConsole).toBe("function")
  })
})