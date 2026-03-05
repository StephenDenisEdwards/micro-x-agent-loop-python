# Micro-X Agent Demo: Job Search App Generation
#
# Shows the agent generating a complete job search application from a prompt,
# then running it to produce a real job report — all in one session.
#
# What this demonstrates:
#   - Natural language prompt to working app
#   - MCP-based code generation with automated testing
#   - MCP tool orchestration (Gmail + LinkedIn)
#   - Cost transparency with /cost command

Output C:/Users/steph/source/repos/micro-x-agent-loop-python/documentation/docs/demos/demo-job-search.gif

Set Shell "cmd.exe"
Set FontSize 14
Set Width 1400
Set Height 750
Set TypingSpeed 30

# Launch the agent
Type "run.bat --config config-standard-no-summarization-sonnet.json"
Enter
Sleep 12s

# Ask the agent to generate a job search app from a prompt file
Type "Generate a job search app using the prompt in C:\Users\steph\source\repos\resources\documents"
Sleep 500ms
Enter

# Wait for mode analysis + file discovery + selection list to appear
Sleep 8s

# Let the viewer read the selection list
Sleep 8s

# Select second item (arrow down once) then confirm
Down
Sleep 3s
Enter

# Wait for code generation (template copy, LLM code gen, validation, test fixing)
# Measured ~2m25s from logs
Sleep 160s

# Let the user read the summary of what was generated
Sleep 8s

# Now run the generated app
Type "yes run it"
Sleep 300ms
Enter

# Wait for run_task MCP call (Gmail search + LinkedIn search + scoring)
# Measured ~1m39s from logs
Sleep 110s

# Let the user read the results
Sleep 10s

# Show cost breakdown
Type "/cost"
Sleep 300ms
Enter

# Let the cost summary render and be readable
Sleep 12s
