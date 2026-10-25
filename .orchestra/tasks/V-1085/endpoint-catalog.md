# ElevenLabs: каталог публично документированных маршрутов

Проверено 2026-10-25 (UTC). Источник индекса: https://elevenlabs.io/docs/llms.txt.

Из 592 страниц API Reference выделено 400 уникальных пар method/path; дубли общего и Agents-справочников объединены. Это карта документации, не перечень прав нашего аккаунта и не результат исполнения API. Все обращения при сборе — GET публичных страниц docs.

HTTP base: `https://api.elevenlabs.io`; WebSocket base для клиентских API: `wss://api.elevenlabs.io`. Исключение `/speech-engine/upstream`: это протокол нашего сервера (`wsUrl`), к которому ElevenLabs подключается клиентом; это не адрес на vendor API. GET в строке WebSocket означает handshake. Статус Legacy означает раздел официального индекса; наличие deprecated-параметра само по себе не делает весь endpoint deprecated. Составные группы наследуют ограничения, цену, пример и неизвестное из соответствующего семейства в [report.md](report.md). Хеши страниц и время получения: [api-inventory.json](sources/api-inventory.json).


## Core Resources > History

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/history` | [Get generated items](https://elevenlabs.io/docs/api-reference/history/list) | В текущем индексе |
| DELETE | `/v1/history/{history_item_id}` | [Delete history item](https://elevenlabs.io/docs/api-reference/history/delete) | В текущем индексе |
| GET | `/v1/history/{history_item_id}` | [Get history item](https://elevenlabs.io/docs/api-reference/history/get) | В текущем индексе |
| GET | `/v1/history/{history_item_id}/audio` | [Get audio from history item](https://elevenlabs.io/docs/api-reference/history/get-audio) | В текущем индексе |
| POST | `/v1/history/download` | [Download history items](https://elevenlabs.io/docs/api-reference/history/download) | В текущем индексе |

## Core Resources > Models

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/models` | [List models](https://elevenlabs.io/docs/api-reference/models/list) | В текущем индексе |

## Core Resources > Tokens

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/single-use-token/{token_type}` | [Create Single Use Token](https://elevenlabs.io/docs/api-reference/tokens/create) | В текущем индексе |

## ElevenAgents > Agents

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/convai/agent/{agent_id}/llm-usage/calculate` | [Calculate expected LLM usage](https://elevenlabs.io/docs/api-reference/agents/calculate) | В текущем индексе |
| GET | `/v1/convai/agents` | [List agents](https://elevenlabs.io/docs/api-reference/agents/list) | В текущем индексе |
| DELETE | `/v1/convai/agents/{agent_id}` | [Delete agent](https://elevenlabs.io/docs/api-reference/agents/delete) | В текущем индексе |
| GET | `/v1/convai/agents/{agent_id}` | [Get agent](https://elevenlabs.io/docs/api-reference/agents/get) | В текущем индексе |
| PATCH | `/v1/convai/agents/{agent_id}` | [Update agent](https://elevenlabs.io/docs/api-reference/agents/update) | В текущем индексе |
| POST | `/v1/convai/agents/{agent_id}/duplicate` | [Duplicate agent](https://elevenlabs.io/docs/api-reference/agents/duplicate) | В текущем индексе |
| GET | `/v1/convai/agents/{agent_id}/link` | [Get link](https://elevenlabs.io/docs/api-reference/agents/get-link) | В текущем индексе |
| POST | `/v1/convai/agents/{agent_id}/simulate-conversation` | [Simulate conversation](https://elevenlabs.io/docs/api-reference/agents/simulate-conversation) | В текущем индексе |
| POST | `/v1/convai/agents/{agent_id}/simulate-conversation/stream` | [Stream simulate conversation](https://elevenlabs.io/docs/api-reference/agents/simulate-conversation-stream) | В текущем индексе |
| POST | `/v1/convai/agents/create` | [Create agent](https://elevenlabs.io/docs/api-reference/agents/create) | В текущем индексе |
| GET | `/v1/convai/agents/summaries` | [Get agent summaries](https://elevenlabs.io/docs/api-reference/agents/get-summaries) | В текущем индексе |

## ElevenAgents > Agents > Branches

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/agents/{agent_id}/branches` | [List agent branches](https://elevenlabs.io/docs/api-reference/agents/branches/list) | В текущем индексе |
| POST | `/v1/convai/agents/{agent_id}/branches` | [Create agent branch](https://elevenlabs.io/docs/api-reference/agents/branches/create) | В текущем индексе |
| GET | `/v1/convai/agents/{agent_id}/branches/{branch_id}` | [Get agent branch](https://elevenlabs.io/docs/api-reference/agents/branches/get) | В текущем индексе |
| PATCH | `/v1/convai/agents/{agent_id}/branches/{branch_id}` | [Update agent branch](https://elevenlabs.io/docs/api-reference/agents/branches/update) | В текущем индексе |
| POST | `/v1/convai/agents/{agent_id}/branches/{branch_id}/rebase` | [Rebase a branch onto main](https://elevenlabs.io/docs/api-reference/agents/branches/rebase) | В текущем индексе |
| GET | `/v1/convai/agents/{agent_id}/branches/{branch_id}/rebase-preview` | [Preview rebased configuration](https://elevenlabs.io/docs/api-reference/agents/branches/preview-rebase) | В текущем индексе |
| POST | `/v1/convai/agents/{agent_id}/branches/{source_branch_id}/merge` | [Merge agent branch](https://elevenlabs.io/docs/api-reference/agents/branches/merge) | В текущем индексе |
| GET | `/v1/convai/agents/{agent_id}/branches/{source_branch_id}/merge-preview` | [Preview merged configuration](https://elevenlabs.io/docs/api-reference/agents/branches/preview-merge) | В текущем индексе |

## ElevenAgents > Agents > Deployments

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/agents/{agent_id}/deployments` | [List Agent Deployments](https://elevenlabs.io/docs/api-reference/agents/deployments/list) | В текущем индексе |
| POST | `/v1/convai/agents/{agent_id}/deployments` | [Create deployment](https://elevenlabs.io/docs/api-reference/agents/deployments/create) | В текущем индексе |

## ElevenAgents > Agents > Drafts

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| DELETE | `/v1/convai/agents/{agent_id}/drafts` | [Delete draft](https://elevenlabs.io/docs/api-reference/agents/drafts/delete) | В текущем индексе |
| POST | `/v1/convai/agents/{agent_id}/drafts` | [Create draft](https://elevenlabs.io/docs/api-reference/agents/drafts/create) | В текущем индексе |

## ElevenAgents > Agents > Hold audio

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| DELETE | `/v1/convai/agents/{agent_id}/hold-audio` | [Delete agent hold audio](https://elevenlabs.io/docs/api-reference/agents/hold-audio/delete) | В текущем индексе |
| POST | `/v1/convai/agents/{agent_id}/hold-audio` | [Post agent hold audio](https://elevenlabs.io/docs/api-reference/agents/hold-audio/create) | В текущем индексе |

## ElevenAgents > Agents > Merge proposals

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/agents/{agent_id}/merge-proposals` | [List Proposals](https://elevenlabs.io/docs/api-reference/agents/merge-proposals/list) | В текущем индексе |
| POST | `/v1/convai/agents/{agent_id}/merge-proposals` | [Create A Merge Proposal](https://elevenlabs.io/docs/api-reference/agents/merge-proposals/create) | В текущем индексе |
| GET | `/v1/convai/agents/{agent_id}/merge-proposals/{merge_proposal_id}` | [Get A Merge Proposal](https://elevenlabs.io/docs/api-reference/agents/merge-proposals/get) | В текущем индексе |
| PATCH | `/v1/convai/agents/{agent_id}/merge-proposals/{merge_proposal_id}` | [Update A Merge Proposal](https://elevenlabs.io/docs/api-reference/agents/merge-proposals/update) | В текущем индексе |
| POST | `/v1/convai/agents/{agent_id}/merge-proposals/{merge_proposal_id}/comments` | [Comment On A Merge Proposal](https://elevenlabs.io/docs/api-reference/agents/merge-proposals/add-comment) | В текущем индексе |
| POST | `/v1/convai/agents/{agent_id}/merge-proposals/{merge_proposal_id}/merge` | [Merge A Merge Proposal](https://elevenlabs.io/docs/api-reference/agents/merge-proposals/merge) | В текущем индексе |
| POST | `/v1/convai/agents/{agent_id}/merge-proposals/{merge_proposal_id}/reviews` | [Review A Merge Proposal](https://elevenlabs.io/docs/api-reference/agents/merge-proposals/submit-review) | В текущем индексе |

## ElevenAgents > Agents > Procedures

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/agents/{agent_id}/branches/{branch_id}/procedures` | [List Procedures](https://elevenlabs.io/docs/api-reference/agents/procedures/list) | В текущем индексе |
| POST | `/v1/convai/agents/{agent_id}/branches/{branch_id}/procedures` | [Create Procedure](https://elevenlabs.io/docs/api-reference/agents/procedures/create) | В текущем индексе |
| DELETE | `/v1/convai/agents/{agent_id}/branches/{branch_id}/procedures/{procedure_id}` | [Remove Procedure](https://elevenlabs.io/docs/api-reference/agents/procedures/remove) | В текущем индексе |
| GET | `/v1/convai/agents/{agent_id}/branches/{branch_id}/procedures/{procedure_id}` | [Get Procedure](https://elevenlabs.io/docs/api-reference/agents/procedures/get) | В текущем индексе |
| DELETE | `/v1/convai/agents/{agent_id}/branches/{branch_id}/procedures/{procedure_id}/draft` | [Delete Procedure Draft](https://elevenlabs.io/docs/api-reference/agents/procedures/delete) | В текущем индексе |
| GET | `/v1/convai/agents/{agent_id}/branches/{branch_id}/procedures/{procedure_id}/draft` | [Get Procedure Draft](https://elevenlabs.io/docs/api-reference/agents/procedures/get-draft) | В текущем индексе |
| PATCH | `/v1/convai/agents/{agent_id}/branches/{branch_id}/procedures/{procedure_id}/draft` | [Update Procedure Draft](https://elevenlabs.io/docs/api-reference/agents/procedures/update) | В текущем индексе |
| POST | `/v1/convai/agents/{agent_id}/branches/{branch_id}/procedures/compile` | [Compile Procedures (legacy)](https://elevenlabs.io/docs/api-reference/agents/procedures/compile) | В текущем индексе |

## ElevenAgents > Agents > Versions

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/agents/{agent_id}/versions/{version_id}` | [Get agent version metadata](https://elevenlabs.io/docs/api-reference/agents/versions/get) | В текущем индексе |

## ElevenAgents > Analytics

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/analytics/live-count` | [Get live count](https://elevenlabs.io/docs/api-reference/analytics/get) | В текущем индексе |

## ElevenAgents > Batch Calling

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| DELETE | `/v1/convai/batch-calling/{batch_id}` | [Delete batch calling job](https://elevenlabs.io/docs/api-reference/batch-calling/delete) | В текущем индексе |
| GET | `/v1/convai/batch-calling/{batch_id}` | [Get batch call information](https://elevenlabs.io/docs/api-reference/batch-calling/get) | В текущем индексе |
| POST | `/v1/convai/batch-calling/{batch_id}/cancel` | [Cancel batch calling job](https://elevenlabs.io/docs/api-reference/batch-calling/cancel) | В текущем индексе |
| GET | `/v1/convai/batch-calling/{batch_id}/export` | [Export batch call results](https://elevenlabs.io/docs/api-reference/batch-calling/export) | В текущем индексе |
| POST | `/v1/convai/batch-calling/{batch_id}/retry` | [Retry batch calling job](https://elevenlabs.io/docs/api-reference/batch-calling/retry) | В текущем индексе |
| POST | `/v1/convai/batch-calling/submit` | [Submit batch calling job](https://elevenlabs.io/docs/api-reference/batch-calling/create) | В текущем индексе |
| GET | `/v1/convai/batch-calling/workspace` | [List workspace batch calling jobs](https://elevenlabs.io/docs/api-reference/batch-calling/list) | В текущем индексе |

## ElevenAgents > Conversations

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/conversation/get-signed-url` | [Get signed URL](https://elevenlabs.io/docs/api-reference/conversations/get-signed-url) | В текущем индексе |
| GET | `/v1/convai/conversation/token` | [Get conversation token](https://elevenlabs.io/docs/api-reference/conversations/get-webrtc-token) | В текущем индексе |
| GET | `/v1/convai/conversations` | [List conversations](https://elevenlabs.io/docs/api-reference/conversations/list) | В текущем индексе |
| DELETE | `/v1/convai/conversations/{conversation_id}` | [Delete conversation](https://elevenlabs.io/docs/api-reference/conversations/delete) | В текущем индексе |
| GET | `/v1/convai/conversations/{conversation_id}` | [Get conversation details](https://elevenlabs.io/docs/api-reference/conversations/get) | В текущем индексе |
| GET | `/v1/convai/conversations/{conversation_id}/audio` | [Get conversation audio](https://elevenlabs.io/docs/api-reference/conversations/get-audio) | В текущем индексе |
| POST | `/v1/convai/conversations/{conversation_id}/feedback` | [Send conversation feedback](https://elevenlabs.io/docs/api-reference/conversations/create) | В текущем индексе |
| POST | `/v1/convai/conversations/{conversation_id}/files` | [Upload conversation file](https://elevenlabs.io/docs/api-reference/conversations/upload-file) | В текущем индексе |
| DELETE | `/v1/convai/conversations/{conversation_id}/files/{file_id}` | [Delete conversation file](https://elevenlabs.io/docs/api-reference/conversations/delete-file) | В текущем индексе |
| GET | `/v1/convai/conversations/{conversation_id}/sip-messages` | [Get SIP messages for a conversation](https://elevenlabs.io/docs/api-reference/conversations/get-sip-messages) | В текущем индексе |
| GET | `/v1/convai/conversations/{conversation_id}/summary` | [Get conversation summary](https://elevenlabs.io/docs/api-reference/conversations/get-summary) | В текущем индексе |
| GET | `/v1/convai/conversations/resolve` | [Resolve conversation reference](https://elevenlabs.io/docs/api-reference/conversations/resolve) | В текущем индексе |
| POST | `/v1/convai/realtime/client_secrets` | [Create realtime client secret](https://elevenlabs.io/docs/api-reference/conversations/create-client-secret) | В текущем индексе |

## ElevenAgents > Conversations > Analysis

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/convai/conversations/{conversation_id}/analysis/evaluations/run` | [Run conversation evaluation](https://elevenlabs.io/docs/api-reference/conversations/analysis/run-evaluation) | В текущем индексе |
| POST | `/v1/convai/conversations/{conversation_id}/analysis/run` | [Run conversation analysis](https://elevenlabs.io/docs/api-reference/conversations/analysis/run-analysis) | В текущем индексе |

## ElevenAgents > Conversations > Messages

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/conversations/messages/smart-search` | [Smart search](https://elevenlabs.io/docs/api-reference/conversations/messages/search) | В текущем индексе |
| GET | `/v1/convai/conversations/messages/text-search` | [Text search](https://elevenlabs.io/docs/api-reference/conversations/messages/text-search) | В текущем индексе |

## ElevenAgents > Conversations > Tags

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/convai/conversations/{conversation_id}/tags` | [Add tag to conversation](https://elevenlabs.io/docs/api-reference/conversations/tags/assign) | В текущем индексе |
| DELETE | `/v1/convai/conversations/{conversation_id}/tags/{tag_id}` | [Remove tag from conversation](https://elevenlabs.io/docs/api-reference/conversations/tags/unassign) | В текущем индексе |
| GET | `/v1/convai/tags` | [List tags](https://elevenlabs.io/docs/api-reference/conversations/tags/list) | В текущем индексе |
| POST | `/v1/convai/tags` | [Create tag](https://elevenlabs.io/docs/api-reference/conversations/tags/create) | В текущем индексе |
| DELETE | `/v1/convai/tags/{tag_id}` | [Delete tag](https://elevenlabs.io/docs/api-reference/conversations/tags/delete) | В текущем индексе |
| GET | `/v1/convai/tags/{tag_id}` | [Get tag](https://elevenlabs.io/docs/api-reference/conversations/tags/get) | В текущем индексе |
| PATCH | `/v1/convai/tags/{tag_id}` | [Update tag](https://elevenlabs.io/docs/api-reference/conversations/tags/update) | В текущем индексе |

## ElevenAgents > Conversations > Topics

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/agents/{agent_id}/topics` | [Get agent conversation topics](https://elevenlabs.io/docs/api-reference/conversations/topics/get) | В текущем индексе |

## ElevenAgents > Environment Variables

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/environment-variables` | [List environment variables](https://elevenlabs.io/docs/api-reference/environment-variables/list) | В текущем индексе |
| POST | `/v1/convai/environment-variables` | [Create environment variable](https://elevenlabs.io/docs/api-reference/environment-variables/create) | В текущем индексе |
| GET | `/v1/convai/environment-variables/{env_var_id}` | [Get environment variable](https://elevenlabs.io/docs/api-reference/environment-variables/get) | В текущем индексе |
| PATCH | `/v1/convai/environment-variables/{env_var_id}` | [Update environment variable](https://elevenlabs.io/docs/api-reference/environment-variables/update) | В текущем индексе |

## ElevenAgents > Environments

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/environments` | [List environments](https://elevenlabs.io/docs/api-reference/environments/list) | В текущем индексе |
| POST | `/v1/convai/environments` | [Create environment](https://elevenlabs.io/docs/api-reference/environments/create) | В текущем индексе |
| DELETE | `/v1/convai/environments/{environment}` | [Delete environment](https://elevenlabs.io/docs/api-reference/environments/delete) | В текущем индексе |

## ElevenAgents > Integrations > Exotel

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/convai/exotel/outbound-call` | [Outbound call via Exotel](https://elevenlabs.io/docs/api-reference/integrations/exotel/outbound-call) | В текущем индексе |

## ElevenAgents > Integrations > Twilio

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/convai/twilio/outbound-call` | [Outbound call via twilio](https://elevenlabs.io/docs/api-reference/integrations/twilio/outbound-call) | В текущем индексе |
| POST | `/v1/convai/twilio/register-call` | [Register call](https://elevenlabs.io/docs/api-reference/integrations/twilio/register-call) | В текущем индексе |

## ElevenAgents > Integrations > WhatsApp

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/convai/whatsapp/outbound-call` | [Outbound call via WhatsApp](https://elevenlabs.io/docs/api-reference/integrations/whats-app/outbound-call) | В текущем индексе |
| POST | `/v1/convai/whatsapp/outbound-message` | [Outbound message via WhatsApp](https://elevenlabs.io/docs/api-reference/integrations/whats-app/outbound-message) | В текущем индексе |

## ElevenAgents > Integrations > WhatsApp > Accounts

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/whatsapp-accounts` | [List WhatsApp accounts](https://elevenlabs.io/docs/api-reference/integrations/whats-app/accounts/list) | В текущем индексе |
| DELETE | `/v1/convai/whatsapp-accounts/{phone_number_id}` | [Delete WhatsApp account](https://elevenlabs.io/docs/api-reference/integrations/whats-app/accounts/delete) | В текущем индексе |
| GET | `/v1/convai/whatsapp-accounts/{phone_number_id}` | [Get WhatsApp account](https://elevenlabs.io/docs/api-reference/integrations/whats-app/accounts/get) | В текущем индексе |
| PATCH | `/v1/convai/whatsapp-accounts/{phone_number_id}` | [Update WhatsApp account](https://elevenlabs.io/docs/api-reference/integrations/whats-app/accounts/update) | В текущем индексе |

## ElevenAgents > Knowledge Base

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/agent/{agent_id}/knowledge-base/size` | [Get knowledge base size](https://elevenlabs.io/docs/api-reference/knowledge-base/size) | В текущем индексе |
| GET | `/v1/convai/knowledge-base/{documentation_id}/dependent-agents` | [Get dependent agents](https://elevenlabs.io/docs/api-reference/knowledge-base/get-agents) | В текущем индексе |
| POST | `/v1/convai/knowledge-base/dependent-agents` | [Get dependent agents for multiple documents](https://elevenlabs.io/docs/api-reference/knowledge-base/dependent-agents-multiple) | В текущем индексе |
| GET | `/v1/convai/knowledge-base/search` | [Search knowledge base](https://elevenlabs.io/docs/api-reference/knowledge-base/search) | В текущем индексе |
| GET | `/v1/convai/knowledge-base/summaries` | [Get knowledge base summaries](https://elevenlabs.io/docs/api-reference/knowledge-base/get-summaries) | В текущем индексе |

## ElevenAgents > Knowledge Base > Crawl jobs

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/knowledge-base/crawl` | [List crawl jobs](https://elevenlabs.io/docs/api-reference/knowledge-base/list-crawl-jobs) | В текущем индексе |
| POST | `/v1/convai/knowledge-base/crawl` | [Create crawl job](https://elevenlabs.io/docs/api-reference/knowledge-base/create-crawl-job) | В текущем индексе |
| GET | `/v1/convai/knowledge-base/crawl/{crawl_job_id}` | [Get crawl job](https://elevenlabs.io/docs/api-reference/knowledge-base/get-crawl-job) | В текущем индексе |
| POST | `/v1/convai/knowledge-base/crawl/{crawl_job_id}/cancel` | [Cancel crawl job](https://elevenlabs.io/docs/api-reference/knowledge-base/cancel-crawl-job) | В текущем индексе |

## ElevenAgents > Knowledge Base > Documents

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/knowledge-base` | [List knowledge base documents](https://elevenlabs.io/docs/api-reference/knowledge-base/list) | В текущем индексе |
| DELETE | `/v1/convai/knowledge-base/{documentation_id}` | [Delete knowledge base document](https://elevenlabs.io/docs/api-reference/knowledge-base/delete) | В текущем индексе |
| GET | `/v1/convai/knowledge-base/{documentation_id}` | [Get knowledge base document](https://elevenlabs.io/docs/api-reference/knowledge-base/get-document) | В текущем индексе |
| PATCH | `/v1/convai/knowledge-base/{documentation_id}` | [Update knowledge base document](https://elevenlabs.io/docs/api-reference/knowledge-base/update) | В текущем индексе |
| GET | `/v1/convai/knowledge-base/{documentation_id}/chunk/{chunk_id}` | [Get document chunk](https://elevenlabs.io/docs/api-reference/knowledge-base/get-chunk) | В текущем индексе |
| GET | `/v1/convai/knowledge-base/{documentation_id}/chunks` | [Get RAG chunks for a document](https://elevenlabs.io/docs/api-reference/knowledge-base/get-chunks) | В текущем индексе |
| GET | `/v1/convai/knowledge-base/{documentation_id}/content` | [Get document content](https://elevenlabs.io/docs/api-reference/knowledge-base/get-content) | В текущем индексе |
| POST | `/v1/convai/knowledge-base/{documentation_id}/refresh` | [Refresh knowledge base document](https://elevenlabs.io/docs/api-reference/knowledge-base/refresh) | В текущем индексе |
| GET | `/v1/convai/knowledge-base/{documentation_id}/source-file-url` | [Get source file URL](https://elevenlabs.io/docs/api-reference/knowledge-base/get-source-file-url) | В текущем индексе |
| PATCH | `/v1/convai/knowledge-base/{documentation_id}/update-file` | [Update document file](https://elevenlabs.io/docs/api-reference/knowledge-base/update-file) | В текущем индексе |
| POST | `/v1/convai/knowledge-base/bulk-delete` | [Bulk delete knowledge base documents](https://elevenlabs.io/docs/api-reference/knowledge-base/bulk-delete) | В текущем индексе |
| POST | `/v1/convai/knowledge-base/file` | [Create knowledge base document from file](https://elevenlabs.io/docs/api-reference/knowledge-base/create-from-file) | В текущем индексе |
| POST | `/v1/convai/knowledge-base/text` | [Create knowledge base document from text](https://elevenlabs.io/docs/api-reference/knowledge-base/create-from-text) | В текущем индексе |
| POST | `/v1/convai/knowledge-base/url` | [Create knowledge base document from URL](https://elevenlabs.io/docs/api-reference/knowledge-base/create-from-url) | В текущем индексе |

## ElevenAgents > Knowledge Base > Folders

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/convai/knowledge-base/{document_id}/move` | [Move document](https://elevenlabs.io/docs/api-reference/knowledge-base/move-document) | В текущем индексе |
| POST | `/v1/convai/knowledge-base/bulk-move` | [Bulk move documents](https://elevenlabs.io/docs/api-reference/knowledge-base/bulk-move) | В текущем индексе |
| POST | `/v1/convai/knowledge-base/folder` | [Create folder](https://elevenlabs.io/docs/api-reference/knowledge-base/create-folder) | В текущем индексе |

## ElevenAgents > Knowledge Base > RAG

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/knowledge-base/{documentation_id}/rag-index` | [Get RAG index](https://elevenlabs.io/docs/api-reference/knowledge-base/get-rag-index) | В текущем индексе |
| POST | `/v1/convai/knowledge-base/{documentation_id}/rag-index` | [Compute RAG index](https://elevenlabs.io/docs/api-reference/knowledge-base/compute-rag-index) | В текущем индексе |
| DELETE | `/v1/convai/knowledge-base/{documentation_id}/rag-index/{rag_index_id}` | [Delete RAG index](https://elevenlabs.io/docs/api-reference/knowledge-base/delete-rag-index) | В текущем индексе |
| GET | `/v1/convai/knowledge-base/rag-index` | [Get RAG index overview](https://elevenlabs.io/docs/api-reference/knowledge-base/rag-index-overview) | В текущем индексе |
| POST | `/v1/convai/knowledge-base/rag-index` | [Compute RAG index in batch](https://elevenlabs.io/docs/api-reference/knowledge-base/compute-rag-index-batch) | В текущем индексе |

## ElevenAgents > LLM

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/convai/llm-usage/calculate` | [Calculate expected LLM usage](https://elevenlabs.io/docs/api-reference/llm/calculate) | В текущем индексе |
| GET | `/v1/convai/llm/list` | [List LLMs](https://elevenlabs.io/docs/api-reference/llm/list) | В текущем индексе |

## ElevenAgents > MCP

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/mcp-servers` | [List MCP servers](https://elevenlabs.io/docs/api-reference/mcp/list) | В текущем индексе |
| POST | `/v1/convai/mcp-servers` | [Create MCP server](https://elevenlabs.io/docs/api-reference/mcp/create) | В текущем индексе |
| DELETE | `/v1/convai/mcp-servers/{mcp_server_id}` | [Delete MCP server](https://elevenlabs.io/docs/api-reference/mcp/delete) | В текущем индексе |
| GET | `/v1/convai/mcp-servers/{mcp_server_id}` | [Get MCP server](https://elevenlabs.io/docs/api-reference/mcp/get) | В текущем индексе |
| PATCH | `/v1/convai/mcp-servers/{mcp_server_id}` | [Update MCP server configuration](https://elevenlabs.io/docs/api-reference/mcp/update) | В текущем индексе |
| GET | `/v1/convai/mcp-servers/{mcp_server_id}/tools` | [List MCP server tools](https://elevenlabs.io/docs/api-reference/mcp/list-tools) | В текущем индексе |

## ElevenAgents > MCP > Approval Policies

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| PATCH | `/v1/convai/mcp-servers/{mcp_server_id}/approval-policy` | [Update MCP server approval policy](https://elevenlabs.io/docs/api-reference/mcp/approval-policies/update) | В текущем индексе |
| POST | `/v1/convai/mcp-servers/{mcp_server_id}/tool-approvals` | [Create MCP server tool approval](https://elevenlabs.io/docs/api-reference/mcp/approval-policies/create) | В текущем индексе |
| DELETE | `/v1/convai/mcp-servers/{mcp_server_id}/tool-approvals/{tool_name}` | [Delete MCP server tool approval](https://elevenlabs.io/docs/api-reference/mcp/approval-policies/delete) | В текущем индексе |

## ElevenAgents > MCP > Tool Configuration

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/convai/mcp-servers/{mcp_server_id}/tool-configs` | [Create configuration override](https://elevenlabs.io/docs/api-reference/mcp/tool-configuration/create) | В текущем индексе |
| DELETE | `/v1/convai/mcp-servers/{mcp_server_id}/tool-configs/{tool_name}` | [Delete configuration override](https://elevenlabs.io/docs/api-reference/mcp/tool-configuration/delete) | В текущем индексе |
| GET | `/v1/convai/mcp-servers/{mcp_server_id}/tool-configs/{tool_name}` | [Get configuration override](https://elevenlabs.io/docs/api-reference/mcp/tool-configuration/get) | В текущем индексе |
| PATCH | `/v1/convai/mcp-servers/{mcp_server_id}/tool-configs/{tool_name}` | [Update configuration override](https://elevenlabs.io/docs/api-reference/mcp/tool-configuration/update) | В текущем индексе |

## ElevenAgents > Phone Numbers

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/phone-numbers` | [List phone numbers](https://elevenlabs.io/docs/api-reference/phone-numbers/list) | В текущем индексе |
| POST | `/v1/convai/phone-numbers` | [Import phone number](https://elevenlabs.io/docs/api-reference/phone-numbers/create) | В текущем индексе |
| DELETE | `/v1/convai/phone-numbers/{phone_number_id}` | [Delete phone number](https://elevenlabs.io/docs/api-reference/phone-numbers/delete) | В текущем индексе |
| GET | `/v1/convai/phone-numbers/{phone_number_id}` | [Get phone number](https://elevenlabs.io/docs/api-reference/phone-numbers/get) | В текущем индексе |
| PATCH | `/v1/convai/phone-numbers/{phone_number_id}` | [Update phone number](https://elevenlabs.io/docs/api-reference/phone-numbers/update) | В текущем индексе |
| GET | `/v1/convai/phone-numbers/{phone_number_id}/sip-messages` | [Get SIP messages for a phone number](https://elevenlabs.io/docs/api-reference/phone-numbers/get-sip-messages) | В текущем индексе |
| GET | `/v1/convai/v2/phone-numbers` | [List Phone Numbers Page](https://elevenlabs.io/docs/api-reference/phone-numbers/list-v-2) | В текущем индексе |

## ElevenAgents > SIP Trunk

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/convai/sip-trunk/outbound-call` | [Outbound call via SIP trunk](https://elevenlabs.io/docs/api-reference/sip-trunk/outbound-call) | В текущем индексе |

## ElevenAgents > Tests

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/agent-testing` | [List tests](https://elevenlabs.io/docs/api-reference/tests/list) | В текущем индексе |
| DELETE | `/v1/convai/agent-testing/{test_id}` | [Delete test](https://elevenlabs.io/docs/api-reference/tests/delete) | В текущем индексе |
| GET | `/v1/convai/agent-testing/{test_id}` | [Get test](https://elevenlabs.io/docs/api-reference/tests/get) | В текущем индексе |
| PUT | `/v1/convai/agent-testing/{test_id}` | [Update test](https://elevenlabs.io/docs/api-reference/tests/update) | В текущем индексе |
| POST | `/v1/convai/agent-testing/create` | [Create test](https://elevenlabs.io/docs/api-reference/tests/create) | В текущем индексе |
| POST | `/v1/convai/agent-testing/summaries` | [Get test summaries](https://elevenlabs.io/docs/api-reference/tests/summaries) | В текущем индексе |
| POST | `/v1/convai/agents/{agent_id}/run-tests` | [Run tests on agent](https://elevenlabs.io/docs/api-reference/tests/run-tests) | В текущем индексе |

## ElevenAgents > Tests > Test Folders

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/convai/agent-testing/bulk-move` | [Bulk move tests to folder](https://elevenlabs.io/docs/api-reference/tests/test-folders/move) | В текущем индексе |
| POST | `/v1/convai/agent-testing/folders` | [Create folder](https://elevenlabs.io/docs/api-reference/tests/test-folders/create) | В текущем индексе |
| DELETE | `/v1/convai/agent-testing/folders/{folder_id}` | [Delete folder](https://elevenlabs.io/docs/api-reference/tests/test-folders/delete) | В текущем индексе |
| GET | `/v1/convai/agent-testing/folders/{folder_id}` | [Get folder](https://elevenlabs.io/docs/api-reference/tests/test-folders/get) | В текущем индексе |
| PATCH | `/v1/convai/agent-testing/folders/{folder_id}` | [Update folder](https://elevenlabs.io/docs/api-reference/tests/test-folders/update) | В текущем индексе |

## ElevenAgents > Tests > Test Invocations

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/test-invocations` | [List test invocations](https://elevenlabs.io/docs/api-reference/tests/test-invocations/list) | В текущем индексе |
| GET | `/v1/convai/test-invocations/{test_invocation_id}` | [Get test invocation](https://elevenlabs.io/docs/api-reference/tests/test-invocations/get) | В текущем индексе |
| POST | `/v1/convai/test-invocations/{test_invocation_id}/cancel` | [Cancel Test Invocation](https://elevenlabs.io/docs/api-reference/tests/test-invocations/cancel) | В текущем индексе |
| POST | `/v1/convai/test-invocations/{test_invocation_id}/resubmit` | [Resubmit test invocation](https://elevenlabs.io/docs/api-reference/tests/test-invocations/resubmit) | В текущем индексе |

## ElevenAgents > Tools

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/tools` | [List tools](https://elevenlabs.io/docs/api-reference/tools/list) | В текущем индексе |
| POST | `/v1/convai/tools` | [Create tool](https://elevenlabs.io/docs/api-reference/tools/create) | В текущем индексе |
| DELETE | `/v1/convai/tools/{tool_id}` | [Delete tool](https://elevenlabs.io/docs/api-reference/tools/delete) | В текущем индексе |
| GET | `/v1/convai/tools/{tool_id}` | [Get tool](https://elevenlabs.io/docs/api-reference/tools/get) | В текущем индексе |
| PATCH | `/v1/convai/tools/{tool_id}` | [Update tool](https://elevenlabs.io/docs/api-reference/tools/update) | В текущем индексе |
| GET | `/v1/convai/tools/{tool_id}/dependent-agents` | [Get dependent agents](https://elevenlabs.io/docs/api-reference/tools/get-dependent-agents) | В текущем индексе |
| GET | `/v1/convai/tools/{tool_id}/executions` | [Get tool executions](https://elevenlabs.io/docs/api-reference/tools/get-executions) | В текущем индексе |

## ElevenAgents > Triage Tickets

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/agents/{agent_id}/triage-tickets` | [List tickets](https://elevenlabs.io/docs/api-reference/triage-tickets/list) | В текущем индексе |
| POST | `/v1/convai/agents/{agent_id}/triage-tickets` | [Create manual ticket](https://elevenlabs.io/docs/api-reference/triage-tickets/create-manual) | В текущем индексе |
| GET | `/v1/convai/agents/{agent_id}/triage-tickets/assignable-users` | [List assignable users](https://elevenlabs.io/docs/api-reference/triage-tickets/list-assignable-users) | В текущем индексе |
| GET | `/v1/convai/triage-tickets` | [List workspace tickets](https://elevenlabs.io/docs/api-reference/triage-tickets/list-for-workspace) | В текущем индексе |
| POST | `/v1/convai/triage-tickets` | [Create conversation ticket](https://elevenlabs.io/docs/api-reference/triage-tickets/create) | В текущем индексе |
| DELETE | `/v1/convai/triage-tickets/{agentqa_ticket_id}` | [Delete ticket](https://elevenlabs.io/docs/api-reference/triage-tickets/delete) | В текущем индексе |
| GET | `/v1/convai/triage-tickets/{agentqa_ticket_id}` | [Get ticket](https://elevenlabs.io/docs/api-reference/triage-tickets/get) | В текущем индексе |
| PATCH | `/v1/convai/triage-tickets/{agentqa_ticket_id}` | [Update ticket](https://elevenlabs.io/docs/api-reference/triage-tickets/update) | В текущем индексе |
| POST | `/v1/convai/triage-tickets/{agentqa_ticket_id}/comments` | [Add comment](https://elevenlabs.io/docs/api-reference/triage-tickets/add-comment) | В текущем индексе |
| POST | `/v1/convai/triage-tickets/{agentqa_ticket_id}/merge` | [Merge tickets](https://elevenlabs.io/docs/api-reference/triage-tickets/merge) | В текущем индексе |
| POST | `/v1/convai/triage-tickets/{agentqa_ticket_id}/turn-comments` | [Add turn comment](https://elevenlabs.io/docs/api-reference/triage-tickets/add-turn-comment) | В текущем индексе |

## ElevenAgents > Users

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/users` | [List users](https://elevenlabs.io/docs/api-reference/users/list) | В текущем индексе |

## ElevenAgents > Widget

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/convai/agents/{agent_id}/avatar` | [Create widget avatar](https://elevenlabs.io/docs/api-reference/widget/create) | В текущем индексе |
| GET | `/v1/convai/agents/{agent_id}/widget` | [Get widget](https://elevenlabs.io/docs/api-reference/widget/get) | В текущем индексе |

## ElevenAgents > Workspace > Dashboard

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/settings/dashboard` | [Get dashboard settings](https://elevenlabs.io/docs/api-reference/workspace/dashboard/get) | В текущем индексе |
| PATCH | `/v1/convai/settings/dashboard` | [Update Convai Dashboard Settings](https://elevenlabs.io/docs/api-reference/workspace/dashboard/update) | В текущем индексе |

## ElevenAgents > Workspace > Secrets

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/secrets` | [Get secrets](https://elevenlabs.io/docs/api-reference/workspace/secrets/list) | В текущем индексе |
| POST | `/v1/convai/secrets` | [Create secret](https://elevenlabs.io/docs/api-reference/workspace/secrets/create) | В текущем индексе |
| DELETE | `/v1/convai/secrets/{secret_id}` | [Delete secret](https://elevenlabs.io/docs/api-reference/workspace/secrets/delete) | В текущем индексе |
| GET | `/v1/convai/secrets/{secret_id}` | [Get secret](https://elevenlabs.io/docs/api-reference/workspace/secrets/get) | В текущем индексе |
| PATCH | `/v1/convai/secrets/{secret_id}` | [Update secret](https://elevenlabs.io/docs/api-reference/workspace/secrets/update) | В текущем индексе |
| GET | `/v1/convai/secrets/{secret_id}/dependencies/{resource_type}` | [Get secret dependencies](https://elevenlabs.io/docs/api-reference/workspace/secrets/get-dependencies) | В текущем индексе |

## ElevenAgents > Workspace > Settings

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/convai/settings` | [Get settings](https://elevenlabs.io/docs/api-reference/workspace/get) | В текущем индексе |
| PATCH | `/v1/convai/settings` | [Update settings](https://elevenlabs.io/docs/api-reference/workspace/update) | В текущем индексе |

## ElevenAPI > Audio Effects

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/audio-effects/catalog` | [Get Audio Effects Catalog](https://elevenlabs.io/docs/api-reference/audio-effects/get-catalog) | В текущем индексе |

## ElevenAPI > Audio Isolation

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/audio-isolation` | [Audio isolation](https://elevenlabs.io/docs/api-reference/audio-isolation/convert) | В текущем индексе |
| GET | `/v1/audio-isolation/history` | [Get Audio Isolation History](https://elevenlabs.io/docs/api-reference/audio-isolation/list) | В текущем индексе |
| DELETE | `/v1/audio-isolation/history/{history_item_id}` | [Delete Audio Isolation History Item](https://elevenlabs.io/docs/api-reference/audio-isolation/delete) | В текущем индексе |
| POST | `/v1/audio-isolation/stream` | [Audio isolation stream](https://elevenlabs.io/docs/api-reference/audio-isolation/stream) | В текущем индексе |

## ElevenAPI > Audio Native

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/audio-native` | [Create audio native project](https://elevenlabs.io/docs/api-reference/audio-native/create) | В текущем индексе |
| POST | `/v1/audio-native/{project_id}/content` | [Update audio native project](https://elevenlabs.io/docs/api-reference/audio-native/update) | В текущем индексе |
| GET | `/v1/audio-native/{project_id}/settings` | [Get Audio Native Project Settings](https://elevenlabs.io/docs/api-reference/audio-native/get-settings) | В текущем индексе |
| POST | `/v1/audio-native/content` | [Update Audio-Native Content From Url](https://elevenlabs.io/docs/api-reference/audio-native/update-content-from-url) | В текущем индексе |

## ElevenAPI > Dubbing

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/dubbing/project` | [List projects](https://elevenlabs.io/docs/api-reference/dubbing/list-projects) | В текущем индексе |
| POST | `/v1/dubbing/project` | [Create project](https://elevenlabs.io/docs/api-reference/dubbing/create-project) | В текущем индексе |
| DELETE | `/v1/dubbing/project/{project_id}` | [Delete project](https://elevenlabs.io/docs/api-reference/dubbing/delete-project) | В текущем индексе |
| GET | `/v1/dubbing/project/{project_id}` | [Get project](https://elevenlabs.io/docs/api-reference/dubbing/get-project) | В текущем индексе |

## ElevenAPI > Dubbing > Language targets

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/dubbing/project/{project_id}/language` | [List language targets](https://elevenlabs.io/docs/api-reference/dubbing/language-targets/list-language-targets) | В текущем индексе |
| POST | `/v1/dubbing/project/{project_id}/language` | [Create language target](https://elevenlabs.io/docs/api-reference/dubbing/language-targets/create-language-target) | В текущем индексе |
| DELETE | `/v1/dubbing/project/{project_id}/language/{language_id}` | [Delete language target](https://elevenlabs.io/docs/api-reference/dubbing/language-targets/delete-language-target) | В текущем индексе |
| GET | `/v1/dubbing/project/{project_id}/language/{language_id}` | [Get language target](https://elevenlabs.io/docs/api-reference/dubbing/language-targets/get-language-target) | В текущем индексе |

## ElevenAPI > Dubbing > Source transcript

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/dubbing/project/{project_id}/transcript` | [Get source transcript](https://elevenlabs.io/docs/api-reference/dubbing/source-transcript/get-source-transcript) | В текущем индексе |
| POST | `/v1/dubbing/project/{project_id}/transcript/segment` | [Add source segment](https://elevenlabs.io/docs/api-reference/dubbing/source-transcript/add-source-segment) | В текущем индексе |
| DELETE | `/v1/dubbing/project/{project_id}/transcript/segment/{segment_id}` | [Delete source segment](https://elevenlabs.io/docs/api-reference/dubbing/source-transcript/delete-source-segment) | В текущем индексе |
| PATCH | `/v1/dubbing/project/{project_id}/transcript/segment/{segment_id}` | [Update source segment](https://elevenlabs.io/docs/api-reference/dubbing/source-transcript/update-source-segment) | В текущем индексе |
| PATCH | `/v1/dubbing/project/{project_id}/transcript/segments` | [Batch update source segments](https://elevenlabs.io/docs/api-reference/dubbing/source-transcript/batch-update-source-segments) | В текущем индексе |

## ElevenAPI > Dubbing > Target transcript

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/dubbing/project/{project_id}/language/{language_id}/transcript` | [Get target transcript](https://elevenlabs.io/docs/api-reference/dubbing/target-transcript/get-target-transcript) | В текущем индексе |
| POST | `/v1/dubbing/project/{project_id}/language/{language_id}/transcript/regenerate` | [Regenerate target](https://elevenlabs.io/docs/api-reference/dubbing/target-transcript/regenerate-target) | В текущем индексе |
| PATCH | `/v1/dubbing/project/{project_id}/language/{language_id}/transcript/segment/{segment_id}` | [Update target segment](https://elevenlabs.io/docs/api-reference/dubbing/target-transcript/update-target-segment) | В текущем индексе |
| PATCH | `/v1/dubbing/project/{project_id}/language/{language_id}/transcript/segments` | [Batch update target segments](https://elevenlabs.io/docs/api-reference/dubbing/target-transcript/batch-update-target-segments) | В текущем индексе |

## ElevenAPI > Forced Alignment

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/forced-alignment` | [Create Forced Alignment](https://elevenlabs.io/docs/api-reference/forced-alignment/create) | В текущем индексе |

## ElevenAPI > Music

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/music` | [Compose music](https://elevenlabs.io/docs/api-reference/music/compose) | В текущем индексе |
| POST | `/v1/music/detailed` | [Compose music with details](https://elevenlabs.io/docs/api-reference/music/compose-detailed) | В текущем индексе |
| POST | `/v1/music/detailed/stream` | [Stream music with details](https://elevenlabs.io/docs/api-reference/music/compose-detailed-stream) | В текущем индексе |
| POST | `/v1/music/plan` | [Create composition plan](https://elevenlabs.io/docs/api-reference/music/create-composition-plan) | В текущем индексе |
| POST | `/v1/music/stem-separation` | [Stem Separation](https://elevenlabs.io/docs/api-reference/music/separate-stems) | В текущем индексе |
| POST | `/v1/music/stream` | [Stream music](https://elevenlabs.io/docs/api-reference/music/stream) | В текущем индексе |
| POST | `/v1/music/upload` | [Upload Music](https://elevenlabs.io/docs/api-reference/music/upload) | В текущем индексе |
| POST | `/v1/music/video-to-music` | [Video To Music](https://elevenlabs.io/docs/api-reference/music/video-to-music) | В текущем индексе |

## ElevenAPI > Music > Finetunes

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/music/finetunes` | [Get Music Finetunes](https://elevenlabs.io/docs/api-reference/music/finetunes/list) | В текущем индексе |
| POST | `/v1/music/finetunes` | [Create Music Finetune](https://elevenlabs.io/docs/api-reference/music/finetunes/create) | В текущем индексе |
| DELETE | `/v1/music/finetunes/{finetune_id}` | [Delete Music Finetune](https://elevenlabs.io/docs/api-reference/music/finetunes/delete) | В текущем индексе |
| GET | `/v1/music/finetunes/{finetune_id}` | [Get Music Finetune](https://elevenlabs.io/docs/api-reference/music/finetunes/get) | В текущем индексе |
| PATCH | `/v1/music/finetunes/{finetune_id}` | [Update Music Finetune](https://elevenlabs.io/docs/api-reference/music/finetunes/update) | В текущем индексе |

## ElevenAPI > Pronunciation Dictionaries

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/pronunciation-dictionaries` | [List pronunciation dictionaries](https://elevenlabs.io/docs/api-reference/pronunciation-dictionaries/list) | В текущем индексе |
| GET | `/v1/pronunciation-dictionaries/{dictionary_id}/{version_id}/download` | [Get pronunciation dictionary by version](https://elevenlabs.io/docs/api-reference/pronunciation-dictionaries/download) | В текущем индексе |
| GET | `/v1/pronunciation-dictionaries/{pronunciation_dictionary_id}` | [Get pronunciation dictionary](https://elevenlabs.io/docs/api-reference/pronunciation-dictionaries/get) | В текущем индексе |
| PATCH | `/v1/pronunciation-dictionaries/{pronunciation_dictionary_id}` | [Update Pronunciation Dictionary](https://elevenlabs.io/docs/api-reference/pronunciation-dictionaries/update) | В текущем индексе |
| POST | `/v1/pronunciation-dictionaries/add-from-file` | [Create a pronunciation dictionary from a file](https://elevenlabs.io/docs/api-reference/pronunciation-dictionaries/create-from-file) | В текущем индексе |
| POST | `/v1/pronunciation-dictionaries/add-from-rules` | [Create a pronunciation dictionary from rules](https://elevenlabs.io/docs/api-reference/pronunciation-dictionaries/create-from-rules) | В текущем индексе |

## ElevenAPI > Pronunciation Dictionaries > Rules

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/pronunciation-dictionaries/{pronunciation_dictionary_id}/add-rules` | [Add pronunciation dictionary rules](https://elevenlabs.io/docs/api-reference/pronunciation-dictionaries/rules/add) | В текущем индексе |
| POST | `/v1/pronunciation-dictionaries/{pronunciation_dictionary_id}/remove-rules` | [Remove pronunciation dictionary rules](https://elevenlabs.io/docs/api-reference/pronunciation-dictionaries/rules/remove) | В текущем индексе |
| POST | `/v1/pronunciation-dictionaries/{pronunciation_dictionary_id}/set-rules` | [Set pronunciation dictionary rules](https://elevenlabs.io/docs/api-reference/pronunciation-dictionaries/rules/set) | В текущем индексе |

## ElevenAPI > Realtime Translation

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| WS GET | `/v1/translation/realtime` | [WebSocket](https://elevenlabs.io/docs/api-reference/realtime-translation/v-1-translation-realtime) | В текущем индексе |

## ElevenAPI > Sound Effects

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/sound-generation` | [Create sound effect](https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert) | В текущем индексе |

## ElevenAPI > Speech Engine

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| WS GET | `/speech-engine/upstream` | [WebSocket](https://elevenlabs.io/docs/api-reference/speech-engine/speech-engine-upstream) | В текущем индексе |
| GET | `/v1/speech-engine` | [List Speech Engines](https://elevenlabs.io/docs/api-reference/speech-engine/list) | В текущем индексе |
| POST | `/v1/speech-engine` | [Create Speech Engine](https://elevenlabs.io/docs/api-reference/speech-engine/create) | В текущем индексе |
| DELETE | `/v1/speech-engine/{speech_engine_id}` | [Delete Speech Engine](https://elevenlabs.io/docs/api-reference/speech-engine/delete) | В текущем индексе |
| GET | `/v1/speech-engine/{speech_engine_id}` | [Get Speech Engine](https://elevenlabs.io/docs/api-reference/speech-engine/get) | В текущем индексе |
| PATCH | `/v1/speech-engine/{speech_engine_id}` | [Update Speech Engine](https://elevenlabs.io/docs/api-reference/speech-engine/update) | В текущем индексе |
| POST | `/v1/speech-engine/{speech_engine_id}/duplicate` | [Duplicate Speech Engine](https://elevenlabs.io/docs/api-reference/speech-engine/duplicate) | В текущем индексе |

## ElevenAPI > Speech to Text

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/speech-to-text` | [Create transcript](https://elevenlabs.io/docs/api-reference/speech-to-text/convert) | В текущем индексе |
| WS GET | `/v1/speech-to-text/realtime` | [Realtime](https://elevenlabs.io/docs/api-reference/speech-to-text/v-1-speech-to-text-realtime) | В текущем индексе |
| DELETE | `/v1/speech-to-text/transcripts/{transcription_id}` | [Delete transcript](https://elevenlabs.io/docs/api-reference/speech-to-text/delete) | В текущем индексе |
| GET | `/v1/speech-to-text/transcripts/{transcription_id}` | [Get transcript](https://elevenlabs.io/docs/api-reference/speech-to-text/get) | В текущем индексе |

## ElevenAPI > Text to Dialogue

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/text-to-dialogue` | [Create dialogue](https://elevenlabs.io/docs/api-reference/text-to-dialogue/convert) | В текущем индексе |
| WS GET | `/v1/text-to-dialogue/multi-stream-input` | [Multi-Context WebSocket](https://elevenlabs.io/docs/api-reference/text-to-dialogue/ttd-multi-websocket) | В текущем индексе |
| POST | `/v1/text-to-dialogue/stream` | [Stream dialogue](https://elevenlabs.io/docs/api-reference/text-to-dialogue/stream) | В текущем индексе |
| WS GET | `/v1/text-to-dialogue/stream-input` | [WebSocket](https://elevenlabs.io/docs/api-reference/text-to-dialogue/ttd-websocket) | В текущем индексе |
| POST | `/v1/text-to-dialogue/stream/with-timestamps` | [Stream dialogue with timestamps](https://elevenlabs.io/docs/api-reference/text-to-dialogue/stream-with-timestamps) | В текущем индексе |
| POST | `/v1/text-to-dialogue/with-timestamps` | [Create dialogue with timestamps](https://elevenlabs.io/docs/api-reference/text-to-dialogue/convert-with-timestamps) | В текущем индексе |

## ElevenAPI > Text to Speech

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/text-to-speech/{voice_id}` | [Create speech](https://elevenlabs.io/docs/api-reference/text-to-speech/convert) | В текущем индексе |
| WS GET | `/v1/text-to-speech/{voice_id}/multi-stream-input` | [Multi-Context WebSocket](https://elevenlabs.io/docs/api-reference/text-to-speech/v-1-text-to-speech-voice-id-multi-stream-input) | В текущем индексе |
| POST | `/v1/text-to-speech/{voice_id}/stream` | [Stream speech](https://elevenlabs.io/docs/api-reference/text-to-speech/stream) | В текущем индексе |
| WS GET | `/v1/text-to-speech/{voice_id}/stream-input` | [WebSocket](https://elevenlabs.io/docs/api-reference/text-to-speech/v-1-text-to-speech-voice-id-stream-input) | В текущем индексе |
| POST | `/v1/text-to-speech/{voice_id}/stream/with-timestamps` | [Stream speech with timing](https://elevenlabs.io/docs/api-reference/text-to-speech/stream-with-timestamps) | В текущем индексе |
| POST | `/v1/text-to-speech/{voice_id}/with-timestamps` | [Create speech with timing](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps) | В текущем индексе |

## ElevenAPI > Voice Changer

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/voice-changer/{voice_id}` | [Voice changer](https://elevenlabs.io/docs/api-reference/speech-to-speech/convert) | В текущем индексе |
| POST | `/v1/voice-changer/{voice_id}/stream` | [Voice changer stream](https://elevenlabs.io/docs/api-reference/speech-to-speech/stream) | В текущем индексе |

## ElevenAPI > Voice Design

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/text-to-voice` | [Create a voice](https://elevenlabs.io/docs/api-reference/text-to-voice/create) | В текущем индексе |
| GET | `/v1/text-to-voice/{generated_voice_id}/stream` | [Stream voice preview](https://elevenlabs.io/docs/api-reference/text-to-voice/stream) | В текущем индексе |
| POST | `/v1/text-to-voice/{voice_id}/remix` | [Remix a voice](https://elevenlabs.io/docs/api-reference/text-to-voice/remix) | В текущем индексе |
| POST | `/v1/text-to-voice/design` | [Design a voice](https://elevenlabs.io/docs/api-reference/text-to-voice/design) | В текущем индексе |

## ElevenAPI > Voices

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/similar-voices` | [List similar voices](https://elevenlabs.io/docs/api-reference/voices/find-similar-voices) | В текущем индексе |
| DELETE | `/v1/voices/{voice_id}` | [Delete voice](https://elevenlabs.io/docs/api-reference/voices/delete) | В текущем индексе |
| GET | `/v1/voices/{voice_id}` | [Get voice](https://elevenlabs.io/docs/api-reference/voices/get) | В текущем индексе |
| POST | `/v1/voices/{voice_id}/edit` | [Edit voice](https://elevenlabs.io/docs/api-reference/voices/update) | В текущем индексе |
| POST | `/v1/voices/{voice_id}/replicate-to-isolated-environment` | [Replicate Voice To Isolated Environment](https://elevenlabs.io/docs/api-reference/voices/replicate-to-isolated-environment) | В текущем индексе |
| GET | `/v2/voices` | [List voices](https://elevenlabs.io/docs/api-reference/voices/search) | В текущем индексе |

## ElevenAPI > Voices > Accents

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/voices/accents` | [Get Voice Accents](https://elevenlabs.io/docs/api-reference/voices/accents/get) | В текущем индексе |

## ElevenAPI > Voices > Collections

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/voices/collections` | [List Voice Collections](https://elevenlabs.io/docs/api-reference/voices/collections/list) | В текущем индексе |
| POST | `/v1/voices/collections` | [Create Voice Collection](https://elevenlabs.io/docs/api-reference/voices/collections/create) | В текущем индексе |
| DELETE | `/v1/voices/collections/{collection_id}` | [Delete Voice Collection](https://elevenlabs.io/docs/api-reference/voices/collections/delete) | В текущем индексе |
| GET | `/v1/voices/collections/{collection_id}` | [Get Voice Collection](https://elevenlabs.io/docs/api-reference/voices/collections/get) | В текущем индексе |
| PATCH | `/v1/voices/collections/{collection_id}` | [Update Voice Collection](https://elevenlabs.io/docs/api-reference/voices/collections/update) | В текущем индексе |
| DELETE | `/v1/voices/collections/{collection_id}/voice/{voice_id}` | [Remove Voice From Collection](https://elevenlabs.io/docs/api-reference/voices/collections/remove-voice) | В текущем индексе |
| POST | `/v1/voices/collections/{collection_id}/voice/{voice_id}` | [Add Voice To Collection](https://elevenlabs.io/docs/api-reference/voices/collections/add-voice) | В текущем индексе |

## ElevenAPI > Voices > IVC

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/voices/add` | [Create IVC voice](https://elevenlabs.io/docs/api-reference/voices/ivc/create) | В текущем индексе |

## ElevenAPI > Voices > PVC

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/voices/pvc` | [Create PVC voice](https://elevenlabs.io/docs/api-reference/voices/pvc/create) | В текущем индексе |
| POST | `/v1/voices/pvc/{voice_id}` | [Update PVC voice](https://elevenlabs.io/docs/api-reference/voices/pvc/update) | В текущем индексе |
| GET | `/v1/voices/pvc/{voice_id}/captcha` | [Get PVC verification captcha](https://elevenlabs.io/docs/api-reference/voices/pvc/verification/captcha) | В текущем индексе |
| POST | `/v1/voices/pvc/{voice_id}/captcha` | [Verify PVC verification captcha](https://elevenlabs.io/docs/api-reference/voices/pvc/verification/captcha/verify) | В текущем индексе |
| POST | `/v1/voices/pvc/{voice_id}/samples` | [Add samples to PVC voice](https://elevenlabs.io/docs/api-reference/voices/pvc/samples/create) | В текущем индексе |
| DELETE | `/v1/voices/pvc/{voice_id}/samples/{sample_id}` | [Delete PVC voice sample](https://elevenlabs.io/docs/api-reference/voices/pvc/samples/delete) | В текущем индексе |
| POST | `/v1/voices/pvc/{voice_id}/samples/{sample_id}` | [Update PVC voice sample](https://elevenlabs.io/docs/api-reference/voices/pvc/samples/update) | В текущем индексе |
| GET | `/v1/voices/pvc/{voice_id}/samples/{sample_id}/audio` | [Get PVC voice sample audio](https://elevenlabs.io/docs/api-reference/voices/pvc/samples/get-audio) | В текущем индексе |
| POST | `/v1/voices/pvc/{voice_id}/samples/{sample_id}/separate-speakers` | [Start speaker separation](https://elevenlabs.io/docs/api-reference/voices/pvc/samples/separate-speakers) | В текущем индексе |
| GET | `/v1/voices/pvc/{voice_id}/samples/{sample_id}/speakers` | [Get PVC speaker separation status](https://elevenlabs.io/docs/api-reference/voices/pvc/samples/get-speaker-separation-status) | В текущем индексе |
| GET | `/v1/voices/pvc/{voice_id}/samples/{sample_id}/speakers/{speaker_id}/audio` | [Get separated speaker audio](https://elevenlabs.io/docs/api-reference/voices/pvc/samples/get-separated-speaker-audio) | В текущем индексе |
| GET | `/v1/voices/pvc/{voice_id}/samples/{sample_id}/waveform` | [Get PVC voice sample waveform](https://elevenlabs.io/docs/api-reference/voices/pvc/samples/get-waveform) | В текущем индексе |
| POST | `/v1/voices/pvc/{voice_id}/train` | [Train PVC voice](https://elevenlabs.io/docs/api-reference/voices/pvc/train) | В текущем индексе |
| POST | `/v1/voices/pvc/{voice_id}/verification` | [Request PVC manual verification](https://elevenlabs.io/docs/api-reference/voices/pvc/verification/request) | В текущем индексе |

## ElevenAPI > Voices > Samples

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| DELETE | `/v1/voices/{voice_id}/samples/{sample_id}` | [Delete voice sample](https://elevenlabs.io/docs/api-reference/voices/samples/delete) | В текущем индексе |
| GET | `/v1/voices/{voice_id}/samples/{sample_id}/audio` | [Get voice sample audio](https://elevenlabs.io/docs/api-reference/voices/samples/get) | В текущем индексе |

## ElevenAPI > Voices > Settings

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/voices/{voice_id}/settings` | [Get voice settings](https://elevenlabs.io/docs/api-reference/voices/settings/get) | В текущем индексе |
| POST | `/v1/voices/{voice_id}/settings/edit` | [Edit voice settings](https://elevenlabs.io/docs/api-reference/voices/settings/update) | В текущем индексе |
| GET | `/v1/voices/settings/default` | [Get default voice settings](https://elevenlabs.io/docs/api-reference/voices/settings/get-default) | В текущем индексе |

## ElevenAPI > Voices > Voice library

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/shared-voices` | [List shared voices](https://elevenlabs.io/docs/api-reference/voices/voice-library/get-shared) | В текущем индексе |
| POST | `/v1/voices/add/{public_user_id}/{voice_id}` | [Add shared voice](https://elevenlabs.io/docs/api-reference/voices/voice-library/share) | В текущем индексе |

## ElevenCreative > Image & Video > Assets

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/assets` | [List Assets](https://elevenlabs.io/docs/api-reference/assets/list) | В текущем индексе |
| POST | `/v1/assets` | [Upload Asset](https://elevenlabs.io/docs/api-reference/assets/create) | В текущем индексе |
| DELETE | `/v1/assets/{asset_id}` | [Delete Asset](https://elevenlabs.io/docs/api-reference/assets/delete) | В текущем индексе |
| GET | `/v1/assets/{asset_id}` | [Get Asset](https://elevenlabs.io/docs/api-reference/assets/get) | В текущем индексе |

## ElevenCreative > Image & Video > Flows > Image

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/flows/image` | [List Image Generations](https://elevenlabs.io/docs/api-reference/flows/image/list) | В текущем индексе |
| POST | `/v1/flows/image` | [Create Image Generation](https://elevenlabs.io/docs/api-reference/flows/image/create) | В текущем индексе |
| GET | `/v1/flows/image/{generation_id}` | [Get Image Generation](https://elevenlabs.io/docs/api-reference/flows/image/get) | В текущем индексе |

## ElevenCreative > Image & Video > Flows > Templates

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/flows/templates` | [List Templates](https://elevenlabs.io/docs/api-reference/flows/templates/list) | В текущем индексе |
| GET | `/v1/flows/templates/{template_id}` | [Get Template](https://elevenlabs.io/docs/api-reference/flows/templates/get) | В текущем индексе |

## ElevenCreative > Image & Video > Flows > Templates > Runs

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/flows/templates/{template_id}/runs` | [List Template Runs](https://elevenlabs.io/docs/api-reference/flows/templates/runs/list) | В текущем индексе |
| POST | `/v1/flows/templates/{template_id}/runs` | [Create Template Run](https://elevenlabs.io/docs/api-reference/flows/templates/runs/create) | В текущем индексе |
| GET | `/v1/flows/templates/{template_id}/runs/{run_id}` | [Get Template Run](https://elevenlabs.io/docs/api-reference/flows/templates/runs/get) | В текущем индексе |

## ElevenCreative > Image & Video > Flows > Text to Speech

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/flows/text-to-speech` | [List Speech Generations](https://elevenlabs.io/docs/api-reference/flows/text-to-speech/list) | В текущем индексе |
| POST | `/v1/flows/text-to-speech` | [Create Speech Generation](https://elevenlabs.io/docs/api-reference/flows/text-to-speech/create) | В текущем индексе |
| GET | `/v1/flows/text-to-speech/{generation_id}` | [Get Speech Generation](https://elevenlabs.io/docs/api-reference/flows/text-to-speech/get) | В текущем индексе |

## ElevenCreative > Image & Video > Flows > Video

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/flows/video` | [List Video Generations](https://elevenlabs.io/docs/api-reference/flows/video/list) | В текущем индексе |
| POST | `/v1/flows/video` | [Create Video Generation](https://elevenlabs.io/docs/api-reference/flows/video/create) | В текущем индексе |
| GET | `/v1/flows/video/{generation_id}` | [Get Video Generation](https://elevenlabs.io/docs/api-reference/flows/video/get) | В текущем индексе |

## ElevenCreative > Studio

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/studio/podcasts` | [Create Podcast](https://elevenlabs.io/docs/api-reference/studio/create-podcast) | В текущем индексе |
| GET | `/v1/studio/projects` | [List Studio Projects](https://elevenlabs.io/docs/api-reference/studio/get-projects) | В текущем индексе |
| POST | `/v1/studio/projects` | [Create Studio Project](https://elevenlabs.io/docs/api-reference/studio/add-project) | В текущем индексе |
| DELETE | `/v1/studio/projects/{project_id}` | [Delete Studio Project](https://elevenlabs.io/docs/api-reference/studio/delete-project) | В текущем индексе |
| GET | `/v1/studio/projects/{project_id}` | [Get Studio Project](https://elevenlabs.io/docs/api-reference/studio/get-project) | В текущем индексе |
| POST | `/v1/studio/projects/{project_id}` | [Update Studio Project](https://elevenlabs.io/docs/api-reference/studio/edit-project) | В текущем индексе |
| GET | `/v1/studio/projects/{project_id}/chapters` | [List Chapters](https://elevenlabs.io/docs/api-reference/studio/get-chapters) | В текущем индексе |
| POST | `/v1/studio/projects/{project_id}/chapters` | [Create Chapter](https://elevenlabs.io/docs/api-reference/studio/add-chapter) | В текущем индексе |
| DELETE | `/v1/studio/projects/{project_id}/chapters/{chapter_id}` | [Delete Chapter](https://elevenlabs.io/docs/api-reference/studio/delete-chapter) | В текущем индексе |
| GET | `/v1/studio/projects/{project_id}/chapters/{chapter_id}` | [Get Chapter](https://elevenlabs.io/docs/api-reference/studio/get-chapter) | В текущем индексе |
| POST | `/v1/studio/projects/{project_id}/chapters/{chapter_id}` | [Update Chapter](https://elevenlabs.io/docs/api-reference/studio/update-chapter) | В текущем индексе |
| POST | `/v1/studio/projects/{project_id}/chapters/{chapter_id}/convert` | [Convert Chapter](https://elevenlabs.io/docs/api-reference/studio/convert-chapter) | В текущем индексе |
| GET | `/v1/studio/projects/{project_id}/chapters/{chapter_id}/snapshots` | [List Chapter Snapshots](https://elevenlabs.io/docs/api-reference/studio/get-chapter-snapshots) | В текущем индексе |
| GET | `/v1/studio/projects/{project_id}/chapters/{chapter_id}/snapshots/{chapter_snapshot_id}` | [Get Chapter Snapshot](https://elevenlabs.io/docs/api-reference/studio/get-chapter-snapshot) | В текущем индексе |
| POST | `/v1/studio/projects/{project_id}/chapters/{chapter_id}/snapshots/{chapter_snapshot_id}/stream` | [Stream Chapter Audio](https://elevenlabs.io/docs/api-reference/studio/stream-chapter-snapshot) | В текущем индексе |
| POST | `/v1/studio/projects/{project_id}/content` | [Update Studio Project Content](https://elevenlabs.io/docs/api-reference/studio/update-content) | В текущем индексе |
| POST | `/v1/studio/projects/{project_id}/convert` | [Convert Studio Project](https://elevenlabs.io/docs/api-reference/studio/convert-project) | В текущем индексе |
| GET | `/v1/studio/projects/{project_id}/muted-tracks` | [Get Project Muted Tracks](https://elevenlabs.io/docs/api-reference/studio/get-muted-tracks) | В текущем индексе |
| POST | `/v1/studio/projects/{project_id}/pronunciation-dictionaries` | [Create Pronunciation Dictionaries](https://elevenlabs.io/docs/api-reference/studio/create-pronunciation-dictionaries) | В текущем индексе |
| GET | `/v1/studio/projects/{project_id}/snapshots` | [List Studio Project Snapshots](https://elevenlabs.io/docs/api-reference/studio/get-snapshots) | В текущем индексе |
| GET | `/v1/studio/projects/{project_id}/snapshots/{project_snapshot_id}` | [Get Project Snapshot](https://elevenlabs.io/docs/api-reference/studio/get-project-snapshot) | В текущем индексе |
| POST | `/v1/studio/projects/{project_id}/snapshots/{project_snapshot_id}/archive` | [Stream Archive With Studio Project Audio](https://elevenlabs.io/docs/api-reference/studio/archive-snapshot) | В текущем индексе |
| POST | `/v1/studio/projects/{project_id}/snapshots/{project_snapshot_id}/stream` | [Stream Studio Project Audio](https://elevenlabs.io/docs/api-reference/studio/stream-snapshot) | В текущем индексе |

## Legacy > Dubbing

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/dubbing` | [List dubs](https://elevenlabs.io/docs/api-reference/legacy/dubbing/list) | Legacy |
| POST | `/v1/dubbing` | [Dub a video or an audio file](https://elevenlabs.io/docs/api-reference/legacy/dubbing/create) | Legacy |
| DELETE | `/v1/dubbing/{dubbing_id}` | [Delete dubbing](https://elevenlabs.io/docs/api-reference/legacy/dubbing/delete) | Legacy |
| GET | `/v1/dubbing/{dubbing_id}` | [Get dubbing](https://elevenlabs.io/docs/api-reference/legacy/dubbing/get) | Legacy |
| GET | `/v1/dubbing/{dubbing_id}/audio/{language_code}` | [Get dubbed file](https://elevenlabs.io/docs/api-reference/legacy/dubbing/audio/get) | Legacy |
| GET | `/v1/dubbing/{dubbing_id}/transcript/{language_code}` | [Get dubbed transcript](https://elevenlabs.io/docs/api-reference/legacy/dubbing/get-transcript-for-dub) | Legacy |
| GET | `/v1/dubbing/{dubbing_id}/transcripts/{language_code}/format/{format_type}` | [Retrieve a transcript](https://elevenlabs.io/docs/api-reference/legacy/dubbing/transcripts/get) | Legacy |

## Legacy > Knowledge Base

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/convai/knowledge-base` | [Add To Knowledge Base](https://elevenlabs.io/docs/api-reference/legacy/knowledge-base/add-to-knowledge-base) | Legacy |

## Legacy > Usage

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/usage/character-stats` | [Get character metrics usage](https://elevenlabs.io/docs/api-reference/legacy/usage/get) | Legacy |

## Legacy > Voices

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/text-to-voice/create-previews` | [Voice design](https://elevenlabs.io/docs/api-reference/legacy/voices/create-previews) | Legacy |
| GET | `/v1/voices` | [List voices](https://elevenlabs.io/docs/api-reference/legacy/voices/get-all) | Legacy |

## Workspace > Analytics

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/workspace/analytics/query/usage-by-product-over-time` | [Get workspace usage](https://elevenlabs.io/docs/api-reference/analytics/workspace/usage) | В текущем индексе |
| POST | `/v1/workspace/analytics/requests` | [List API requests](https://elevenlabs.io/docs/api-reference/analytics/workspace/requests) | В текущем индексе |

## Workspace > API Keys

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/workspaces/api-keys/disable` | [Disable API key](https://elevenlabs.io/docs/api-reference/api-keys/disable) | В текущем индексе |
| POST | `/v1/workspaces/api-keys/third-party-disabling` | [Set workspace third-party disabling policy](https://elevenlabs.io/docs/api-reference/api-keys/set-third-party-disabling-policy) | В текущем индексе |

## Workspace > Service Accounts

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/service-accounts` | [Get service accounts](https://elevenlabs.io/docs/api-reference/service-accounts/list) | В текущем индексе |
| POST | `/v1/service-accounts` | [Create Service Account](https://elevenlabs.io/docs/api-reference/service-accounts/create) | В текущем индексе |

## Workspace > Service Accounts > API Keys

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/service-accounts/{service_account_user_id}/api-keys` | [Get API keys](https://elevenlabs.io/docs/api-reference/service-accounts/api-keys/list) | В текущем индексе |
| POST | `/v1/service-accounts/{service_account_user_id}/api-keys` | [Create API key](https://elevenlabs.io/docs/api-reference/service-accounts/api-keys/create) | В текущем индексе |
| DELETE | `/v1/service-accounts/{service_account_user_id}/api-keys/{api_key_id}` | [Delete API key](https://elevenlabs.io/docs/api-reference/service-accounts/api-keys/delete) | В текущем индексе |
| PATCH | `/v1/service-accounts/{service_account_user_id}/api-keys/{api_key_id}` | [Update API key](https://elevenlabs.io/docs/api-reference/service-accounts/api-keys/update) | В текущем индексе |
| POST | `/v1/service-accounts/{service_account_user_id}/api-keys/{api_key_id}/disable` | [Disable Service Account Api Key](https://elevenlabs.io/docs/api-reference/service-accounts/api-keys/disable) | В текущем индексе |

## Workspace > User

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/user` | [Get user](https://elevenlabs.io/docs/api-reference/user/get) | В текущем индексе |

## Workspace > User > Subscription

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/user/subscription` | [Get user subscription](https://elevenlabs.io/docs/api-reference/user/subscription/get) | В текущем индексе |

## Workspace > Webhooks

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/workspace/webhooks` | [List Workspace Webhooks](https://elevenlabs.io/docs/api-reference/webhooks/list) | В текущем индексе |
| POST | `/v1/workspace/webhooks` | [Create Workspace Webhook](https://elevenlabs.io/docs/api-reference/webhooks/create) | В текущем индексе |
| DELETE | `/v1/workspace/webhooks/{webhook_id}` | [Delete Workspace Webhook](https://elevenlabs.io/docs/api-reference/webhooks/delete) | В текущем индексе |
| PATCH | `/v1/workspace/webhooks/{webhook_id}` | [Update Workspace Webhook](https://elevenlabs.io/docs/api-reference/webhooks/update) | В текущем индексе |

## Workspace > Workspace > Audit Logs

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/workspace/audit-logs` | [List audit logs](https://elevenlabs.io/docs/api-reference/workspace/audit-logs/list) | В текущем индексе |

## Workspace > Workspace > Auth Connections

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/workspace/auth-connections` | [Get Workspace Auth Connections](https://elevenlabs.io/docs/api-reference/workspace/auth-connections/list) | В текущем индексе |
| POST | `/v1/workspace/auth-connections` | [Create Workspace Auth Connection](https://elevenlabs.io/docs/api-reference/workspace/auth-connections/create) | В текущем индексе |
| DELETE | `/v1/workspace/auth-connections/{auth_connection_id}` | [Delete Workspace Auth Connection](https://elevenlabs.io/docs/api-reference/workspace/auth-connections/delete) | В текущем индексе |
| PATCH | `/v1/workspace/auth-connections/{auth_connection_id}` | [Update Workspace Auth Connection](https://elevenlabs.io/docs/api-reference/workspace/auth-connections/update) | В текущем индексе |

## Workspace > Workspace > Groups

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/workspace/groups` | [List workspace groups](https://elevenlabs.io/docs/api-reference/workspace/groups/list) | В текущем индексе |
| GET | `/v1/workspace/groups/search` | [Search user group](https://elevenlabs.io/docs/api-reference/workspace/groups/search) | В текущем индексе |

## Workspace > Workspace > Groups > Members

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| POST | `/v1/workspace/groups/{group_id}/members` | [Add member to user group](https://elevenlabs.io/docs/api-reference/workspace/groups/members/add) | В текущем индексе |
| POST | `/v1/workspace/groups/{group_id}/members/remove` | [Remove member from user group](https://elevenlabs.io/docs/api-reference/workspace/groups/members/remove) | В текущем индексе |

## Workspace > Workspace > Invites

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| DELETE | `/v1/workspace/invites` | [Delete invite](https://elevenlabs.io/docs/api-reference/workspace/invites/delete) | В текущем индексе |
| POST | `/v1/workspace/invites/add` | [Invite user](https://elevenlabs.io/docs/api-reference/workspace/invites/create) | В текущем индексе |
| POST | `/v1/workspace/invites/add-bulk` | [Invite Multiple Users](https://elevenlabs.io/docs/api-reference/workspace/invites/create-batch) | В текущем индексе |

## Workspace > Workspace > Members

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/workspace/members` | [Get Workspace Members](https://elevenlabs.io/docs/api-reference/workspace/members/list) | В текущем индексе |
| POST | `/v1/workspace/members` | [Update member](https://elevenlabs.io/docs/api-reference/workspace/members/update) | В текущем индексе |

## Workspace > Workspace > Resources

| Метод | Путь | Операция / источник | Статус |
| --- | --- | --- | --- |
| GET | `/v1/workspace/resources/{resource_id}` | [Get Resource](https://elevenlabs.io/docs/api-reference/workspace/resources/get) | В текущем индексе |
| POST | `/v1/workspace/resources/{resource_id}/share` | [Share Workspace Resource](https://elevenlabs.io/docs/api-reference/workspace/resources/share) | В текущем индексе |
| POST | `/v1/workspace/resources/{resource_id}/unshare` | [Unshare Workspace Resource](https://elevenlabs.io/docs/api-reference/workspace/resources/unshare) | В текущем индексе |

## Дополнение из официального guide

`WS GET /v1/convai/realtime` — [OpenAI Realtime compatibility](https://elevenlabs.io/docs/eleven-agents/guides/openai-realtime-compatibility), модели `eleven_realtime_v1_mini` / `eleven_realtime_v1_max`. В исходном индексе это guide, а не отдельная строка API reference.

`WS GET /v1/convai/conversation?agent_id={agent_id}` — [Agents WebSocket guide](https://elevenlabs.io/docs/eleven-agents/libraries/web-sockets); дополнительный канал из guide, без утверждения о его выполнении.
