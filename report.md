# System_Knowledge_Agent — Winter '27 release readiness: 95/100 (Green)

- Definition: Agent Script, github.com/dev-ankit08/POC-TestAgent@main @ `1fd8f0a`
- Project API version: 67.0 (Summer '26)
- Release assessed: Winter '27

## Executive summary

The agent itself keeps working in Winter '27, but its integration foundation needs attention: the Named Credential it uses to call the Tooling API sits on OAuth/Connected App technology that Salesforce is retiring over the next several release cycles, and the underlying reasoning models may be rerouted twice in the coming year. Winter '27 also brings several Agentforce Builder and channel-customization features (multi-agent orchestration, per-connection instructions, agent memory, version compare/merge) that this single-purpose employee agent could adopt to become more discoverable, more configurable per channel, and easier to iterate on safely. No dependency in this agent is broken by this release today, but action is needed before 2027 to keep the Tooling API credential supported and to stay ahead of scheduled AI model reroutes.

## Agent profile (from your repository)

**Business use case:** Employee-facing Agentforce agent (Slack + Lightning panel) that explains how the Health Insurance CRM Salesforce org currently works to developers and business analysts, answering questions about custom objects, fields, Apex classes and triggers using live org metadata read at question time - no Knowledge articles, retriever, or static snapshot.

**Capabilities:**
- search_system_components: keyword search across custom objects, fields, Apex classes and triggers
- describe_custom_object: object description, sharing model, relationships, automation summary, optional field list
- describe_custom_field: field type, formula, picklist values, flags, relationships, Apex usage
- explain_apex_component: Apex class/trigger purpose, methods, data touched, call graph, optional source
- trace_object_automation: trigger -> handler -> service chain per DML operation, downstream cascades, batch/REST/invocable entry points
- map_object_relationships: master-detail/lookup relationships, ownership chains, cross-object Apex automation links, whole-data-model view
- Slack thread context resolution (pronoun/topic disambiguation, prompt-injection resistance)

**Key metadata:**
- Apex classes: SystemKnowledgeService, SystemKnowledgeSearchAction, SystemKnowledgeObjectAction, SystemKnowledgeFieldAction, SystemKnowledgeApexAction, SystemKnowledgeAutomationAction, SystemKnowledgeRelationshipAction, ApexSourceAnalyzer, ToolingMetadataReader
- ~20 domain custom objects (Claim__c, Policy__c, Appeal__c, Prior_Authorization__c, Provider__c, Health_Plan__c, etc.) and their triggers/handlers/services
- PermissionSet: System_Knowledge_Agent_Access (agent access + 6 action class accesses)
- Named Credential: SystemKnowledge_Tooling (Tooling API access via External Client App / Client Credentials OAuth)
- AiAuthoringBundle: System_Knowledge_Agent (Agent Script, AgentforceEmployeeAgent type)
- Channels: Slack (thread mentions) and Lightning panel
- StaticResource: SystemKnowledgeCatalog (referenced in metadata inventory but agent explicitly states no static snapshot/data library is used)

**Impact value:** Gives developers and business analysts fast, grounded, always-current answers about the org's data model and Apex automation (no stale docs), reducing time spent reading code/schema manually and reducing incorrect assumptions about business rules during incident triage and onboarding.

## 🔴 Breaking / must fix

### [Medium] Legacy Agent Metadata Types Still Required While Orgs Are on Mixed API Versions

- **Where:** System_Knowledge_Agent.agent (AiAuthoringBundle)
- **Why:** The agent's Apex classes are pinned at API version 62.0 while the sfdx project/agent report API version 67.0; the new simplified agent metadata types require both source and target orgs to be on API 68.0.
- **Fix:** Until both the sandbox and production org are upgraded to API 68.0, continue using the current AiAuthoringBundle/Bot/BotVersion metadata types for this agent rather than the new simplified types when moving it between orgs.

> To use the new metadata types to move agents between orgs, both orgs must be in API version 68.0. While your sandbox org is in Winter ʼ27 and your production org is in Summer ʼ26, continue to use the previous metadata types.

Source: *Agentforce and Generative AI*, [p. 173 (PDF p. 177)](https://help.salesforce.com/s/articleView?id=release-notes.salesforce_release_notes.htm&release=264&type=5#page=177)

### [Low] Developer Console No Longer Visible by Default

- **Where:** Developer tooling used to maintain SystemKnowledgeService.cls, ApexSourceAnalyzer.cls, ToolingMetadataReader.cls and other Apex classes
- **Why:** Developers who currently debug this agent's ~30 Apex classes/19 triggers via Developer Console will not find it enabled by default in Winter '27.
- **Fix:** Enable Web Console or explicitly re-enable Developer Console in Setup (Setup > Development > Web Console) for teams maintaining this agent's Apex.

> In Winter '27, The Developer Console option is not visible by default in Setup. To enable the Developer Console option in Setup, navigate to Setup, enter Development in the Quick Find box, and select Web Console.

Source: *Platform*, [p. 766 (PDF p. 770)](https://help.salesforce.com/s/articleView?id=release-notes.salesforce_release_notes.htm&release=264&type=5#page=770)

## 🟡 Upcoming changes needing action

### [High] Connected Apps Retirement - Must Migrate to External Client Apps — Available Winter '27, enforced for production instances in Summer '27

- **Impact:** The agent's Tooling API access (SystemKnowledge_Tooling Named Credential) is described as backed by an External Client App/Connected App using OAuth Client Credentials. If the underlying principal is still a legacy Connected App, it will stop receiving support and bug fixes.
- **Action:** Confirm SystemKnowledge_Tooling's OAuth principal is (or is migrated to) a true External Client App, not a legacy Connected App, before Summer '27.

> Keep your integrations supported by migrating to external client apps. In Summer '27, Salesforce is ending support for connected apps. Connected apps will keep working, but Salesforce will no longer fix bugs or provide support for the integrations and authorization flows that use them.

Source: *Identity and Access Management*, [p. 950 (PDF p. 954)](https://help.salesforce.com/s/articleView?id=release-notes.salesforce_release_notes.htm&release=264&type=5#page=954)

### [Medium] OAuth 2.0 Username-Password Flow Retirement — Enforced February 20, 2027

- **Impact:** If SystemKnowledge_Tooling's connected app/external client app configuration uses the username-password OAuth flow anywhere, that integration breaks outright once enforced.
- **Action:** Verify the Named Credential's OAuth flow is Client Credentials (as documented) and not username-password, before Feb 20, 2027.

> When this release update is enforced, we'll stop supporting the OAuth 2.0 username-password flow for connected apps. This update will break all connected app integrations that use this flow.

Source: *Identity and Access Management*, [p. 952 (PDF p. 956)](https://help.salesforce.com/s/articleView?id=release-notes.salesforce_release_notes.htm&release=264&type=5#page=956)

### [Low] OAuth User-Agent and Hybrid User-Agent Flow Retirement — Enforced February 20, 2027

- **Impact:** Any part of the Tooling API integration stack still on user-agent or hybrid user-agent OAuth flows will stop working.
- **Action:** Confirm client credentials or web-server flow with PKCE is used, not user-agent flows, before enforcement.

> Salesforce is retiring the OAuth user-agent flow and the OAuth hybrid user-agent flow. For better security, update your integrations to use the OAuth web-server flow or hybrid web-server flow with the Proof Key for Code Exchange (PKCE) extension.

Source: *Identity and Access Management*, [p. 953 (PDF p. 957)](https://help.salesforce.com/s/articleView?id=release-notes.salesforce_release_notes.htm&release=264&type=5#page=957)

### [Medium] Refresh Token Idle Time-to-Live Limited to 30 Days — Enforced in sandboxes starting Oct 21, 2026; production/scratch/Developer orgs starting Nov 4, 2026

- **Impact:** If the SystemKnowledge_Tooling OAuth principal relies on refresh tokens, tokens idle more than 30 days will be revoked, which could cause Tooling API callouts from ToolingMetadataReader to fail until reauthorized.
- **Action:** Ensure the Tooling integration either uses Client Credentials flow (no stored refresh token) or is exercised frequently enough to avoid the 30-day idle expiry, and monitor for callout failures after enforcement.

> With the enforced idle time-to-live (TTL) setting, refresh tokens expire if they haven't been used for 30 days. At the time of enforcement, Salesforce revokes all existing access tokens and immediately expires refresh tokens that have been idle for more than 30 days.

Source: *Identity and Access Management*, [p. 954 (PDF p. 958)](https://help.salesforce.com/s/articleView?id=release-notes.salesforce_release_notes.htm&release=264&type=5#page=958)

### [Medium] Sharing Recalculation Becomes Asynchronous After Group/Role Updates — Enforced in Spring '27

- **Impact:** trace_object_automation and explain_apex_component report on Apex trigger/service call chains (e.g., PolicyTriggerHandler, PolicyMemberTriggerHandler); if any of that Apex assumes synchronous sharing recalculation after group/role changes, the underlying code can break, making the agent's descriptions of automation inaccurate.
- **Action:** Review Apex automation for synchronous dependency on sharing recalculation and test before Spring '27 enforcement.

> To optimize performance after large-scale updates to groups or roles, Salesforce now performs some sharing recalculations asynchronously. If Apex code and flows require that share records be updated immediately, the code and flows can break when this release update is enforced.

Source: *Platform*, [p. 773 (PDF p. 777)](https://help.salesforce.com/s/articleView?id=release-notes.salesforce_release_notes.htm&release=264&type=5#page=777)

### [Medium] GPT-5 Family and O3/O3-Pro Model Reroute — Starting December 11, 2026

- **Impact:** If the AgentforceEmployeeAgent's reasoning/generation is backed by GPT-5 family or O3/O3-Pro models, the reroute could change answer style, latency, or quality for org-metadata explanations.
- **Action:** Confirm which model the agent uses and validate agent test results after the reroute date.

> Supported Models: GPT-5 Family (GPT-5, GPT-5-Mini, GPT-5-Nano, GPT-5-Pro) and O3 / O3-Pro Reroute Date Approaching (Added the week of September 21, 2026) Models will be rerouted starting December 11, 2026.

Source: *Release Note Changes*, [p. 6 (PDF p. 10)](https://help.salesforce.com/s/articleView?id=release-notes.salesforce_release_notes.htm&release=264&type=5#page=10)

### [Medium] Gemini 2.5 Pro/Flash/Flash-Lite Model Reroute — Starting the week of October 20, 2026

- **Impact:** If the agent uses Gemini 2.5 Pro, Flash, or Flash-Lite for reasoning, this reroute could affect the quality/behavior of generated explanations.
- **Action:** Confirm model dependency and re-test after reroute date.

> Supported Models: Gemini 2.5 Pro, Flash, and Flash-Lite Reroute Date Approaching (Added the week of August 24, 2026) Models will be rerouted starting the week of October 20, 2026.

Source: *Release Note Changes*, [p. 6 (PDF p. 10)](https://help.salesforce.com/s/articleView?id=release-notes.salesforce_release_notes.htm&release=264&type=5#page=10)

### [Low] OAuth 2.0 Device Flow Restricted to Local External Client Apps — November 30, 2026

- **Impact:** Part of the broader OAuth tightening relevant to the External Client App backing SystemKnowledge_Tooling; the device flow will only work for apps with a localhost callback URL.
- **Action:** Confirm the Tooling integration does not rely on the device flow, or reconfigure before enforcement.

> Restrict the OAuth 2.0 Device Flow to Local External Client Apps (Release Update) To secure the OAuth 2.0 device flow, Salesforce is restricting this flow to local external client apps with a localhost callback URL.

Source: *Release Updates*, [p. 155 (PDF p. 159)](https://help.salesforce.com/s/articleView?id=release-notes.salesforce_release_notes.htm&release=264&type=5#page=159)

## 🟢 Recommended enhancements

### Multi-Agent Orchestration for Agentforce (Generally Available)

- **Applies to:** System_Knowledge_Agent.agent (single start_agent block, no subagents today)
- **Benefit:** Connect your Agentforce agent with other specialized Agentforce agents in your Salesforce org so they collaborate on complex tasks to deliver amazing outcomes for your business.

> Extend your agent's capabilities with Multi-Agent Orchestration for Agentforce. Connect your Agentforce agent with other specialized Agentforce agents in your Salesforce org. Together they collaborate on complex tasks to deliver amazing outcomes for your business.

Source: *Agentforce and Generative AI*, [p. 176 (PDF p. 180)](https://help.salesforce.com/s/articleView?id=release-notes.salesforce_release_notes.htm&release=264&type=5#page=180)

### Help Agents Remember What Matters to Your Users (Generally Available)

- **Applies to:** Slack thread context resolution (pronoun/topic disambiguation)
- **Benefit:** Feature available on a rolling basis for Salesforce orgs upgraded to Winter '27, letting the agent retain relevant user context beyond a single thread.

> Agentforce Development: Help Agents Remember What Matters to Your Users (Generally Available) (Added the week of September 21, 2026) Feature available on a rolling basis for Salesforce orgs upgraded to Winter '27 starting the week of September 21, 2026.

Source: *Release Note Changes*, [p. 7 (PDF p. 11)](https://help.salesforce.com/s/articleView?id=release-notes.salesforce_release_notes.htm&release=264&type=5#page=11)

### Customize Agent Behavior Across Channels with Connection Instructions

- **Applies to:** Slack and Lightning panel channel configuration in System_Knowledge_Agent.agent
- **Benefit:** Lets the agent tailor tone/behavior differently per channel (e.g., terser Slack replies vs. richer Lightning panel answers) instead of one instruction set for both.

> Customize Agent Behavior Across Channels with Connection Instructions

Source: *Agentforce and Generative AI*, [p. 35 (PDF p. 39)](https://help.salesforce.com/s/articleView?id=release-notes.salesforce_release_notes.htm&release=264&type=5#page=39)

### Control How Agent Action Outputs Appear on a Connection

- **Applies to:** Action outputs (details field) with is_displayable False / filter_from_agent False on all six SystemKnowledge*Action classes
- **Benefit:** Gives per-connection control over how action output is surfaced, refining the current blanket suppression of raw details output.

> Agentforce Connections: Control How Agent Action Outputs Appear on a Connection (Added the week of September 7, 2026) Feature available starting the week of September 7, 2026.

Source: *Release Note Changes*, [p. 7 (PDF p. 11)](https://help.salesforce.com/s/articleView?id=release-notes.salesforce_release_notes.htm&release=264&type=5#page=11)

### Easily Compare and Merge Agent Versions in Agentforce Builder

- **Applies to:** System_Knowledge_Agent.agent (Agent Script source, single agent file)
- **Benefit:** Copy improvements from one agent version to another with a few clicks, comparing and merging changes in Canvas and Script view - useful when iterating on the agent's reasoning instructions and action wiring.

> Copy improvements from one agent version to another with a few clicks. You can now compare two versions and merge changes from one into another in Canvas and Script view.

Source: *Agentforce and Generative AI*, [p. 161 (PDF p. 165)](https://help.salesforce.com/s/articleView?id=release-notes.salesforce_release_notes.htm&release=264&type=5#page=165)

### Move Agents Between Orgs More Easily with Simplified Agent Metadata Types

- **Applies to:** System_Knowledge_Agent.agent AiAuthoringBundle deployment
- **Benefit:** Simplifies moving the agent bundle between orgs once both orgs are upgraded to the required API version.

> Agentforce Development: Move Agents Between Orgs More Easily with Simplified Agent Metadata Types (Added the week of August 24, 2026) This change is available starting with preview sandboxes the week of August 24, 2026.

Source: *Release Note Changes*, [p. 7 (PDF p. 11)](https://help.salesforce.com/s/articleView?id=release-notes.salesforce_release_notes.htm&release=264&type=5#page=11)

### Agent Picker for Agentforce Employee Agent Lists Connected-Subagent Agents First

- **Applies to:** System_Knowledge_Agent.agent (AgentforceEmployeeAgent type)
- **Benefit:** Improves discoverability: the picker lists agents with connected subagents first, then individual agents, sorted by creation date, showing only the active version - relevant to how end users find this employee agent.

> Agent picker for the Agentforce Employee agent (AEA) lists agents with connected subagents first, then individual agents. Both are sorted by creation date with the oldest first. The list shows only the active version of each agent.

Source: *Agentforce and Generative AI*, [p. 177 (PDF p. 181)](https://help.salesforce.com/s/articleView?id=release-notes.salesforce_release_notes.htm&release=264&type=5#page=181)

### Apex Symbol API (beta)

- **Applies to:** ApexSourceAnalyzer.cls regex-based Apex parsing used by explain_apex_component
- **Benefit:** Provides compiler-accurate metadata for classes, interfaces, methods, and triggers, explicitly positioned to ground setup agents answering admin questions about code - a more robust replacement for the agent's fragile regex-based source parsing.

> Access comprehensive Apex type information with the Apex Symbol API (beta). This Tooling API REST resource returns detailed metadata for built-in, custom, and dynamic Apex types, such as classes, interfaces, methods, and triggers. Use this API to power code completion in IDEs, provide context for AI agents generating Apex code, or ground setup agents answering admin questions about code.

Source: *Platform*, [p. 711 (PDF p. 715)](https://help.salesforce.com/s/articleView?id=release-notes.salesforce_release_notes.htm&release=264&type=5#page=715)

### Increased Apex Heap Limits

- **Applies to:** SystemKnowledgeService.cls (MAX_OUTPUT 14000-char truncation, ApexSourceAnalyzer full-source parsing, map_object_relationships whole-data-model output)
- **Benefit:** Higher synchronous and asynchronous heap limits reduce the risk of runtime heap errors when the agent builds large describe/automation/relationship outputs.

> The Apex heap limit for synchronous transactions increases from 6 MB to 10 MB, and the limit for asynchronous transactions increases from 12 MB to 25 MB.

Source: *Platform*, [p. 704 (PDF p. 708)](https://help.salesforce.com/s/articleView?id=release-notes.salesforce_release_notes.htm&release=264&type=5#page=708)

### Targeted Recompilation of Only Invalid Apex Classes and Triggers

- **Applies to:** ToolingMetadataReader.cls and the ~50 Apex classes / 19 triggers analyzed by the agent
- **Benefit:** Returns compilation results for Apex classes and triggers with validation errors instead of recompiling the entire org, which can be used to detect and surface stale or broken Apex components more efficiently.

> Return compilation results for Apex classes and triggers with validation errors, instead of recompiling the entire org. Access the compilation results through Setup or the Tooling API endpoint.

Source: *Platform*, [p. 713 (PDF p. 717)](https://help.salesforce.com/s/articleView?id=release-notes.salesforce_release_notes.htm&release=264&type=5#page=717)

### Named Credentials Support for Custom CA Certificates

- **Applies to:** SystemKnowledge_Tooling Named Credential
- **Benefit:** Named credential callouts can now succeed against servers whose certificates are signed by a private or internal CA, removing a prior source of callout failure.

> Named credentials can now establish secure connections to servers whose certificates are signed by a private or internal CA (certificate authority). Previously, named credential callouts failed if the server certificate didn't chain to a Salesforce-trusted root authority.

Source: *Named Credentials*, [p. 956 (PDF p. 960)](https://help.salesforce.com/s/articleView?id=release-notes.salesforce_release_notes.htm&release=264&type=5#page=960)

### Security Center External Client Apps Metric

- **Applies to:** SystemKnowledge_Tooling Named Credential / External Client App
- **Benefit:** Provides detailed visibility into authentication and security policy settings - including authorization dates, granted scopes, and usage data - for the external app backing the agent's Tooling API integration.

> Security Center includes an External Client Apps metric for tracking external app configurations across your organization's connected Salesforce tenants. The metric provides detailed visibility into authentication and security policy settings—including authorization dates, granted scopes, and usage data—for each tenant where apps are installed.

Source: *Security Center*, [p. 967 (PDF p. 971)](https://help.salesforce.com/s/articleView?id=release-notes.salesforce_release_notes.htm&release=264&type=5#page=971)

## How the release notes were read

- Pages read: **1096 of 1096** PDF pages, in 19 chunks (6 priority chunk(s) read first).
- Priority topics: Agentforce, Agent Script, AIforce, Claude, Einstein, Generative AI, AI, LLM, large language model, Prompt Builder, prompt template, Model Context Protocol, MCP, Atlas Reasoning, agent action, Data 360, Data Cloud, retriever, Trust Layer
- Candidate findings: 47 found while reading, 3 dropped because the quote was not on the cited page.
- Priority sections:
  - **Salesforce Winter '27 Release Notes** (printed pages 1-4): 5.0 priority-topic mentions per page (Agentforce x7, AI x5, AIforce x2, Generative AI x2)
  - **Release Note Changes** (printed pages 5-31): 8.0 priority-topic mentions per page (Agentforce x97, AI x67, Data 360 x21, MCP x9)
  - **Agentforce and Generative AI** (printed pages 158-177): title names Agentforce, Generative AI, AI
  - **AIforce** (printed pages 178-205): title names AIforce
  - **Data 360** (printed pages 324-341): title names Data 360
  - **Deployment** (printed pages 342-342): 6.0 priority-topic mentions per page (Data 360 x6)
  - **Sales** (printed pages 908-938): 7.2 priority-topic mentions per page (Agentforce x106, Einstein x73, AI x15, Claude x14)
  - **Salesforce Suites** (printed pages 939-942): 5.2 priority-topic mentions per page (Agentforce x12, AI x5, Data 360 x3, Generative AI x1)
  - **Slack Integrations** (printed pages 1087-1088): 8.5 priority-topic mentions per page (Agentforce x12, AI x2, MCP x2, Model Context Protocol x1)

## Agent and dependencies scanned (from your repository)

- `force-app/main/default/aiAuthoringBundles/System_Knowledge_Agent/System_Knowledge_Agent.agent`
- `force-app/main/default/aiAuthoringBundles/System_Knowledge_Agent/System_Knowledge_Agent.bundle-meta.xml`
- `force-app/main/default/classes/ApexSourceAnalyzer.cls`
- `force-app/main/default/classes/ApexSourceAnalyzer.cls-meta.xml`
- `force-app/main/default/classes/AppealService.cls`
- `force-app/main/default/classes/AppealService.cls-meta.xml`
- `force-app/main/default/classes/BeneficiaryServiceTest.cls`
- `force-app/main/default/classes/BeneficiaryServiceTest.cls-meta.xml`
- `force-app/main/default/classes/CaseAssignmentService.cls`
- `force-app/main/default/classes/CaseAssignmentService.cls-meta.xml`
- `force-app/main/default/classes/ClaimAdjudicationBatch.cls`
- `force-app/main/default/classes/ClaimAdjudicationBatch.cls-meta.xml`
- `force-app/main/default/classes/ClaimDiagnosisService.cls`
- `force-app/main/default/classes/ClaimDiagnosisService.cls-meta.xml`
- `force-app/main/default/classes/ClaimDiagnosisServiceTest.cls`
- `force-app/main/default/classes/ClaimDiagnosisServiceTest.cls-meta.xml`
- `force-app/main/default/classes/ClaimDiagnosisTriggerHandler.cls`
- `force-app/main/default/classes/ClaimDiagnosisTriggerHandler.cls-meta.xml`
- `force-app/main/default/classes/ClaimLineItemTriggerHandler.cls`
- `force-app/main/default/classes/ClaimLineItemTriggerHandler.cls-meta.xml`
- `force-app/main/default/classes/ClaimRestService.cls`
- `force-app/main/default/classes/ClaimRestService.cls-meta.xml`
- `force-app/main/default/classes/ClaimService.cls`
- `force-app/main/default/classes/ClaimService.cls-meta.xml`
- `force-app/main/default/classes/ClaimTriggerHandler.cls`
- `force-app/main/default/classes/ClaimTriggerHandler.cls-meta.xml`
- `force-app/main/default/classes/CoverageBenefitTriggerHandler.cls`
- `force-app/main/default/classes/CoverageBenefitTriggerHandler.cls-meta.xml`
- `force-app/main/default/classes/DiagnosisCodeTriggerHandler.cls`
- `force-app/main/default/classes/DiagnosisCodeTriggerHandler.cls-meta.xml`
- `force-app/main/default/classes/GrievanceServiceTest.cls`
- `force-app/main/default/classes/GrievanceServiceTest.cls-meta.xml`
- `force-app/main/default/classes/HealthInsuranceTestDataFactory.cls`
- `force-app/main/default/classes/HealthInsuranceTestDataFactory.cls-meta.xml`
- `force-app/main/default/classes/HealthPlanService.cls`
- `force-app/main/default/classes/HealthPlanService.cls-meta.xml`
- `force-app/main/default/classes/HealthPlanTriggerHandler.cls`
- `force-app/main/default/classes/HealthPlanTriggerHandler.cls-meta.xml`
- `force-app/main/default/classes/MedicalCodeService.cls`
- `force-app/main/default/classes/MedicalCodeService.cls-meta.xml`
- `force-app/main/default/classes/MedicalCodeServiceTest.cls`
- `force-app/main/default/classes/MedicalCodeServiceTest.cls-meta.xml`
- `force-app/main/default/classes/PlanBenefitService.cls`
- `force-app/main/default/classes/PlanBenefitService.cls-meta.xml`
- `force-app/main/default/classes/PlanBenefitTriggerHandler.cls`
- `force-app/main/default/classes/PlanBenefitTriggerHandler.cls-meta.xml`
- `force-app/main/default/classes/PlanConfigurationServiceTest.cls`
- `force-app/main/default/classes/PlanConfigurationServiceTest.cls-meta.xml`
- `force-app/main/default/classes/PolicyMemberService.cls`
- `force-app/main/default/classes/PolicyMemberService.cls-meta.xml`
- `force-app/main/default/classes/PolicyMemberServiceTest.cls`
- `force-app/main/default/classes/PolicyMemberServiceTest.cls-meta.xml`
- `force-app/main/default/classes/PolicyMemberTriggerHandler.cls`
- `force-app/main/default/classes/PolicyMemberTriggerHandler.cls-meta.xml`
- `force-app/main/default/classes/PolicyService.cls`
- `force-app/main/default/classes/PolicyService.cls-meta.xml`
- `force-app/main/default/classes/PolicyTriggerHandler.cls`
- `force-app/main/default/classes/PolicyTriggerHandler.cls-meta.xml`
- `force-app/main/default/classes/PremiumBatchProcessor.cls`
- `force-app/main/default/classes/PremiumBatchProcessor.cls-meta.xml`
- `force-app/main/default/classes/PremiumPaymentScheduler.cls`
- `force-app/main/default/classes/PremiumPaymentScheduler.cls-meta.xml`
- `force-app/main/default/classes/PremiumPaymentTriggerHandler.cls`
- `force-app/main/default/classes/PremiumPaymentTriggerHandler.cls-meta.xml`
- `force-app/main/default/classes/PriorAuthorizationService.cls`
- `force-app/main/default/classes/PriorAuthorizationService.cls-meta.xml`
- `force-app/main/default/classes/PriorAuthorizationTriggerHandler.cls`
- `force-app/main/default/classes/PriorAuthorizationTriggerHandler.cls-meta.xml`
- `force-app/main/default/classes/ProcedureCodeTriggerHandler.cls`
- `force-app/main/default/classes/ProcedureCodeTriggerHandler.cls-meta.xml`
- `force-app/main/default/classes/ProviderNetworkMemberService.cls`
- `force-app/main/default/classes/ProviderNetworkMemberService.cls-meta.xml`
- `force-app/main/default/classes/ProviderNetworkMemberTriggerHandler.cls`
- `force-app/main/default/classes/ProviderNetworkMemberTriggerHandler.cls-meta.xml`
- `force-app/main/default/classes/ProviderNetworkService.cls`
- `force-app/main/default/classes/ProviderNetworkService.cls-meta.xml`
- `force-app/main/default/classes/ProviderNetworkTriggerHandler.cls`
- `force-app/main/default/classes/ProviderNetworkTriggerHandler.cls-meta.xml`
- `force-app/main/default/classes/ProviderService.cls`
- `force-app/main/default/classes/ProviderService.cls-meta.xml`
- `force-app/main/default/classes/ProviderServiceTest.cls`
- `force-app/main/default/classes/ProviderServiceTest.cls-meta.xml`
- `force-app/main/default/classes/ProviderTriggerHandler.cls`
- `force-app/main/default/classes/ProviderTriggerHandler.cls-meta.xml`
- `force-app/main/default/classes/RecordValidationUtil.cls`
- `force-app/main/default/classes/RecordValidationUtil.cls-meta.xml`
- `force-app/main/default/classes/SystemKnowledgeApexAction.cls`
- `force-app/main/default/classes/SystemKnowledgeApexAction.cls-meta.xml`
- `force-app/main/default/classes/SystemKnowledgeAutomationAction.cls`
- `force-app/main/default/classes/SystemKnowledgeAutomationAction.cls-meta.xml`
- `force-app/main/default/classes/SystemKnowledgeFieldAction.cls`
- `force-app/main/default/classes/SystemKnowledgeFieldAction.cls-meta.xml`
- `force-app/main/default/classes/SystemKnowledgeObjectAction.cls`
- `force-app/main/default/classes/SystemKnowledgeObjectAction.cls-meta.xml`
- `force-app/main/default/classes/SystemKnowledgeRelationshipAction.cls`
- `force-app/main/default/classes/SystemKnowledgeRelationshipAction.cls-meta.xml`
- `force-app/main/default/classes/SystemKnowledgeSearchAction.cls`
- `force-app/main/default/classes/SystemKnowledgeSearchAction.cls-meta.xml`
- `force-app/main/default/classes/SystemKnowledgeService.cls`
- `force-app/main/default/classes/SystemKnowledgeService.cls-meta.xml`
- `force-app/main/default/classes/SystemKnowledgeServiceTest.cls`
- `force-app/main/default/classes/SystemKnowledgeServiceTest.cls-meta.xml`
- `force-app/main/default/classes/ToolingMetadataReader.cls`
- `force-app/main/default/classes/ToolingMetadataReader.cls-meta.xml`
- `force-app/main/default/classes/TriggerHandler.cls`
- `force-app/main/default/classes/TriggerHandler.cls-meta.xml`
- `force-app/main/default/objects/Appeal__c/Appeal__c.object-meta.xml`
- `force-app/main/default/objects/Appeal__c/fields/Claim__c.field-meta.xml`
- `force-app/main/default/objects/Appeal__c/fields/Status__c.field-meta.xml`
- `force-app/main/default/objects/Beneficiary__c/fields/Contact__c.field-meta.xml`
- `force-app/main/default/objects/Beneficiary__c/fields/Policy__c.field-meta.xml`
- `force-app/main/default/objects/Claim_Diagnosis__c/Claim_Diagnosis__c.object-meta.xml`
- `force-app/main/default/objects/Claim_Diagnosis__c/fields/Claim__c.field-meta.xml`
- `force-app/main/default/objects/Claim_Diagnosis__c/fields/Diagnosis_Code__c.field-meta.xml`
- `force-app/main/default/objects/Claim_Diagnosis__c/fields/Diagnosis_Sequence__c.field-meta.xml`
- `force-app/main/default/objects/Claim_Diagnosis__c/fields/Is_Primary__c.field-meta.xml`
- `force-app/main/default/objects/Claim_Line_Item__c/Claim_Line_Item__c.object-meta.xml`
- `force-app/main/default/objects/Claim_Line_Item__c/fields/Allowed_Amount__c.field-meta.xml`
- `force-app/main/default/objects/Claim_Line_Item__c/fields/Claim__c.field-meta.xml`
- `force-app/main/default/objects/Claim_Line_Item__c/fields/Denial_Reason__c.field-meta.xml`
- `force-app/main/default/objects/Claim_Line_Item__c/fields/Paid_Amount__c.field-meta.xml`
- `force-app/main/default/objects/Claim_Line_Item__c/fields/Procedure_Code__c.field-meta.xml`
- `force-app/main/default/objects/Claim__c/Claim__c.object-meta.xml`
- `force-app/main/default/objects/Claim__c/fields/Claim_Status__c.field-meta.xml`
- `force-app/main/default/objects/Claim__c/fields/Claim_Type__c.field-meta.xml`
- `force-app/main/default/objects/Claim__c/fields/Copay_Amount__c.field-meta.xml`
- `force-app/main/default/objects/Claim__c/fields/Date_Submitted__c.field-meta.xml`
- `force-app/main/default/objects/Claim__c/fields/Date_of_Service__c.field-meta.xml`
- `force-app/main/default/objects/Claim__c/fields/Denial_Reason__c.field-meta.xml`
- `force-app/main/default/objects/Claim__c/fields/In_Network__c.field-meta.xml`
- `force-app/main/default/objects/Claim__c/fields/Member_Responsibility__c.field-meta.xml`
- `force-app/main/default/objects/Claim__c/fields/Policy_Member__c.field-meta.xml`
- `force-app/main/default/objects/Claim__c/fields/Policy__c.field-meta.xml`
- `force-app/main/default/objects/Claim__c/fields/Prior_Authorization__c.field-meta.xml`
- `force-app/main/default/objects/Claim__c/fields/Provider__c.field-meta.xml`
- `force-app/main/default/objects/Claim__c/fields/Total_Allowed_Amount__c.field-meta.xml`
- `force-app/main/default/objects/Claim__c/fields/Total_Billed_Amount__c.field-meta.xml`
- `force-app/main/default/objects/Claim__c/fields/Total_Paid_Amount__c.field-meta.xml`
- `force-app/main/default/objects/Coverage_Benefit__c/Coverage_Benefit__c.object-meta.xml`
- `force-app/main/default/objects/Coverage_Benefit__c/fields/Annual_Limit__c.field-meta.xml`
- `force-app/main/default/objects/Coverage_Benefit__c/fields/Benefit_Code__c.field-meta.xml`
- `force-app/main/default/objects/Coverage_Benefit__c/fields/Requires_Prior_Auth__c.field-meta.xml`
- `force-app/main/default/objects/Coverage_Benefit__c/fields/Waiting_Period_Days__c.field-meta.xml`
- `force-app/main/default/objects/Diagnosis_Code__c/Diagnosis_Code__c.object-meta.xml`
- `force-app/main/default/objects/Diagnosis_Code__c/fields/Effective_Date__c.field-meta.xml`
- `force-app/main/default/objects/Diagnosis_Code__c/fields/Is_Billable__c.field-meta.xml`
- `force-app/main/default/objects/Diagnosis_Code__c/fields/Termination_Date__c.field-meta.xml`
- `force-app/main/default/objects/Employer_Group__c/fields/Effective_Date__c.field-meta.xml`
- `force-app/main/default/objects/Employer_Group__c/fields/Group_Number__c.field-meta.xml`
- `force-app/main/default/objects/Employer_Group__c/fields/Status__c.field-meta.xml`
- `force-app/main/default/objects/Employer_Group__c/fields/Waiting_Period_Days__c.field-meta.xml`
- `force-app/main/default/objects/Enrollment__c/fields/Contact__c.field-meta.xml`
- `force-app/main/default/objects/Enrollment__c/fields/Effective_Date__c.field-meta.xml`
- `force-app/main/default/objects/Enrollment__c/fields/Health_Plan__c.field-meta.xml`
- `force-app/main/default/objects/Enrollment__c/fields/Status__c.field-meta.xml`
- `force-app/main/default/objects/Grievance__c/fields/Status__c.field-meta.xml`
- `force-app/main/default/objects/Health_Plan__c/Health_Plan__c.object-meta.xml`
- `force-app/main/default/objects/Health_Plan__c/fields/Coinsurance_Percent__c.field-meta.xml`
- `force-app/main/default/objects/Health_Plan__c/fields/Deductible_Family__c.field-meta.xml`
- `force-app/main/default/objects/Health_Plan__c/fields/Deductible_Individual__c.field-meta.xml`
- `force-app/main/default/objects/Health_Plan__c/fields/Effective_Date__c.field-meta.xml`
- `force-app/main/default/objects/Health_Plan__c/fields/End_Date__c.field-meta.xml`
- `force-app/main/default/objects/Health_Plan__c/fields/Monthly_Premium__c.field-meta.xml`
- `force-app/main/default/objects/Health_Plan__c/fields/Out_of_Pocket_Max_Family__c.field-meta.xml`
- `force-app/main/default/objects/Health_Plan__c/fields/Out_of_Pocket_Max_Individual__c.field-meta.xml`
- `force-app/main/default/objects/Health_Plan__c/fields/Plan_Code__c.field-meta.xml`
- `force-app/main/default/objects/Health_Plan__c/fields/Status__c.field-meta.xml`
- `force-app/main/default/objects/Plan_Benefit__c/Plan_Benefit__c.object-meta.xml`
- `force-app/main/default/objects/Plan_Benefit__c/fields/Annual_Visit_Limit__c.field-meta.xml`
- `force-app/main/default/objects/Plan_Benefit__c/fields/Coinsurance_Percent__c.field-meta.xml`
- `force-app/main/default/objects/Plan_Benefit__c/fields/Copay_Amount__c.field-meta.xml`
- `force-app/main/default/objects/Plan_Benefit__c/fields/Coverage_Benefit__c.field-meta.xml`
- `force-app/main/default/objects/Plan_Benefit__c/fields/Effective_Date__c.field-meta.xml`
- `force-app/main/default/objects/Plan_Benefit__c/fields/Health_Plan__c.field-meta.xml`
- `force-app/main/default/objects/Plan_Benefit__c/fields/In_Network__c.field-meta.xml`
- `force-app/main/default/objects/Plan_Benefit__c/fields/Network_Tier__c.field-meta.xml`
- `force-app/main/default/objects/Plan_Benefit__c/fields/Out_of_Network_Coinsurance__c.field-meta.xml`
- `force-app/main/default/objects/Plan_Benefit__c/fields/Requires_Prior_Auth__c.field-meta.xml`
- `force-app/main/default/objects/Policy_Member__c/Policy_Member__c.object-meta.xml`
- `force-app/main/default/objects/Policy_Member__c/fields/Contact__c.field-meta.xml`
- `force-app/main/default/objects/Policy_Member__c/fields/Coverage_End_Date__c.field-meta.xml`
- `force-app/main/default/objects/Policy_Member__c/fields/Coverage_Start_Date__c.field-meta.xml`
- `force-app/main/default/objects/Policy_Member__c/fields/Is_Primary_Subscriber__c.field-meta.xml`
- `force-app/main/default/objects/Policy_Member__c/fields/Member_Number__c.field-meta.xml`
- `force-app/main/default/objects/Policy_Member__c/fields/Policy__c.field-meta.xml`
- `force-app/main/default/objects/Policy_Member__c/fields/Relationship_to_Primary__c.field-meta.xml`
- `force-app/main/default/objects/Policy_Member__c/fields/Status__c.field-meta.xml`
- `force-app/main/default/objects/Policy__c/Policy__c.object-meta.xml`
- `force-app/main/default/objects/Policy__c/fields/Annual_Premium__c.field-meta.xml`
- `force-app/main/default/objects/Policy__c/fields/Effective_Date__c.field-meta.xml`
- `force-app/main/default/objects/Policy__c/fields/Grace_Period_End__c.field-meta.xml`
- `force-app/main/default/objects/Policy__c/fields/Health_Plan__c.field-meta.xml`
- `force-app/main/default/objects/Policy__c/fields/Monthly_Premium__c.field-meta.xml`
- `force-app/main/default/objects/Policy__c/fields/Status__c.field-meta.xml`
- `force-app/main/default/objects/Policy__c/fields/Subscriber_ID__c.field-meta.xml`
- `force-app/main/default/objects/Policy__c/fields/Termination_Date__c.field-meta.xml`
- `force-app/main/default/objects/Policy__c/fields/Total_Members__c.field-meta.xml`
- `force-app/main/default/objects/Premium_Payment__c/Premium_Payment__c.object-meta.xml`
- `force-app/main/default/objects/Premium_Payment__c/fields/Policy__c.field-meta.xml`
- `force-app/main/default/objects/Premium_Payment__c/fields/Status__c.field-meta.xml`
- `force-app/main/default/objects/Prior_Authorization__c/Prior_Authorization__c.object-meta.xml`
- `force-app/main/default/objects/Prior_Authorization__c/fields/Denial_Reason__c.field-meta.xml`
- `force-app/main/default/objects/Prior_Authorization__c/fields/Effective_Date__c.field-meta.xml`
- `force-app/main/default/objects/Prior_Authorization__c/fields/Expiration_Date__c.field-meta.xml`
- `force-app/main/default/objects/Prior_Authorization__c/fields/Policy_Member__c.field-meta.xml`
- `force-app/main/default/objects/Prior_Authorization__c/fields/Procedure_Code__c.field-meta.xml`
- `force-app/main/default/objects/Prior_Authorization__c/fields/Provider__c.field-meta.xml`
- `force-app/main/default/objects/Prior_Authorization__c/fields/Requested_Date__c.field-meta.xml`
- `force-app/main/default/objects/Prior_Authorization__c/fields/Status__c.field-meta.xml`
- `force-app/main/default/objects/Procedure_Code__c/Procedure_Code__c.object-meta.xml`
- `force-app/main/default/objects/Procedure_Code__c/fields/Effective_Date__c.field-meta.xml`
- `force-app/main/default/objects/Procedure_Code__c/fields/Requires_Prior_Auth__c.field-meta.xml`
- `force-app/main/default/objects/Procedure_Code__c/fields/Termination_Date__c.field-meta.xml`
- `force-app/main/default/objects/Provider_Network_Member__c/Provider_Network_Member__c.object-meta.xml`
- `force-app/main/default/objects/Provider_Network_Member__c/fields/Capitation_Rate__c.field-meta.xml`
- `force-app/main/default/objects/Provider_Network_Member__c/fields/Contract_Type__c.field-meta.xml`
- `force-app/main/default/objects/Provider_Network_Member__c/fields/Effective_Date__c.field-meta.xml`
- `force-app/main/default/objects/Provider_Network_Member__c/fields/End_Date__c.field-meta.xml`
- `force-app/main/default/objects/Provider_Network_Member__c/fields/In_Network_Status__c.field-meta.xml`
- `force-app/main/default/objects/Provider_Network_Member__c/fields/Provider_Network__c.field-meta.xml`
- `force-app/main/default/objects/Provider_Network_Member__c/fields/Provider__c.field-meta.xml`
- `force-app/main/default/objects/Provider_Network__c/Provider_Network__c.object-meta.xml`
- `force-app/main/default/objects/Provider_Network__c/fields/Effective_Date__c.field-meta.xml`
- `force-app/main/default/objects/Provider_Network__c/fields/Network_Code__c.field-meta.xml`
- `force-app/main/default/objects/Provider_Network__c/fields/Provider_Count__c.field-meta.xml`
- `force-app/main/default/objects/Provider_Network__c/fields/Status__c.field-meta.xml`
- `force-app/main/default/objects/Provider_Network__c/fields/Termination_Date__c.field-meta.xml`
- `force-app/main/default/objects/Provider__c/Provider__c.object-meta.xml`
- `force-app/main/default/objects/Provider__c/fields/Credentialing_Date__c.field-meta.xml`
- `force-app/main/default/objects/Provider__c/fields/NPI_Number__c.field-meta.xml`
- `force-app/main/default/objects/Provider__c/fields/Recredentialing_Due__c.field-meta.xml`
- `force-app/main/default/objects/Provider__c/fields/Status__c.field-meta.xml`
- `force-app/main/default/permissionsets/System_Knowledge_Agent_Access.permissionset-meta.xml`
- `force-app/main/default/triggers/AppealTrigger.trigger`
- `force-app/main/default/triggers/AppealTrigger.trigger-meta.xml`
- `force-app/main/default/triggers/BeneficiaryTrigger.trigger`
- `force-app/main/default/triggers/BeneficiaryTrigger.trigger-meta.xml`
- `force-app/main/default/triggers/ClaimDiagnosisTrigger.trigger`
- `force-app/main/default/triggers/ClaimDiagnosisTrigger.trigger-meta.xml`
- `force-app/main/default/triggers/ClaimLineItemTrigger.trigger`
- `force-app/main/default/triggers/ClaimLineItemTrigger.trigger-meta.xml`
- `force-app/main/default/triggers/ClaimTrigger.trigger`
- `force-app/main/default/triggers/ClaimTrigger.trigger-meta.xml`
- `force-app/main/default/triggers/CoverageBenefitTrigger.trigger`
- `force-app/main/default/triggers/CoverageBenefitTrigger.trigger-meta.xml`
- `force-app/main/default/triggers/DiagnosisCodeTrigger.trigger`
- `force-app/main/default/triggers/DiagnosisCodeTrigger.trigger-meta.xml`
- `force-app/main/default/triggers/EmployerGroupTrigger.trigger`
- `force-app/main/default/triggers/EmployerGroupTrigger.trigger-meta.xml`
- `force-app/main/default/triggers/GrievanceTrigger.trigger`
- `force-app/main/default/triggers/GrievanceTrigger.trigger-meta.xml`
- `force-app/main/default/triggers/HealthPlanTrigger.trigger`
- `force-app/main/default/triggers/HealthPlanTrigger.trigger-meta.xml`
- `force-app/main/default/triggers/PlanBenefitTrigger.trigger`
- `force-app/main/default/triggers/PlanBenefitTrigger.trigger-meta.xml`
- `force-app/main/default/triggers/PolicyMemberTrigger.trigger`
- `force-app/main/default/triggers/PolicyMemberTrigger.trigger-meta.xml`
- `force-app/main/default/triggers/PolicyTrigger.trigger`
- `force-app/main/default/triggers/PolicyTrigger.trigger-meta.xml`
- `force-app/main/default/triggers/PremiumPaymentTrigger.trigger`
- `force-app/main/default/triggers/PremiumPaymentTrigger.trigger-meta.xml`
- `force-app/main/default/triggers/PriorAuthorizationTrigger.trigger`
- `force-app/main/default/triggers/PriorAuthorizationTrigger.trigger-meta.xml`
- `force-app/main/default/triggers/ProcedureCodeTrigger.trigger`
- `force-app/main/default/triggers/ProcedureCodeTrigger.trigger-meta.xml`
- `force-app/main/default/triggers/ProviderNetworkMemberTrigger.trigger`
- `force-app/main/default/triggers/ProviderNetworkMemberTrigger.trigger-meta.xml`
- `force-app/main/default/triggers/ProviderNetworkTrigger.trigger`
- `force-app/main/default/triggers/ProviderNetworkTrigger.trigger-meta.xml`
- `force-app/main/default/triggers/ProviderTrigger.trigger`
- `force-app/main/default/triggers/ProviderTrigger.trigger-meta.xml`

## Notes

- All 1096 PDF pages of the release notes were read per reading_coverage; no pages were skipped.
- Three candidate findings were marked 'candidates_unverified' in the input; only quotes independently confirmed against the supplied candidate text were kept.
- No static-check findings were provided in this run (static_findings was empty), so all items here come solely from release-notes candidates matched against the agent dossier.
- Several near-duplicate candidates (e.g., multiple mentions of Connected App retirement, OAuth flow retirements, Agentforce Platform Enabled by Default, and Compare/Merge Agent Versions appearing in both the Release Note Changes summary and the full Agentforce and Generative AI section) were merged into single findings to avoid double-counting.
- The dossier's own apiVersion mismatch (Apex pinned at v62.0 vs project v67.0) is a repository-detected condition; the release notes' related guidance on API-version requirements for the new simplified agent metadata types (page 173) is reported as a breaking issue, but no release note explicitly deprecates API v62.0 Apex compilation itself.
- Score: 100 -5 Medium: Legacy Agent Metadata Types Still Required While Orgs Are on Mixed API Versions

_Evidence: official Salesforce Winter '27 release notes only. "p." is the printed page number and "PDF p." the page in the downloaded PDF; links open the official release notes._
