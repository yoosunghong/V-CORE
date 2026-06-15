# PAI Chatbot Backend API 명세서 (v2)
**Version**: 0.1.0
**Description**: Smart farm digital-twin chatbot backend demo service.

## 1. API 목록 요약

| 분류 | HTTP Method | Endpoint | 기능 설명 |
| :--- | :--- | :--- | :--- |
| system | `GET` | `/health` | Health |
| dashboard | `GET` | `/dashboard/overlay` | Dashboard Overlay |
| unreal | `POST` | `/unreal/zones/{zone_id}/focus` | Focus Unreal Zone |
| chat | `POST` | `/chat/sessions` | Create Session |
| chat | `GET` | `/chat/sessions` | List Sessions |
| chat | `GET` | `/chat/sessions/{session_id}/messages` | List Session Messages |
| chat | `POST` | `/chat/messages` | Post Chat Message |
| events | `POST` | `/events/robot-command` | Receive Robot Event |

---

## 2. 상세 엔드포인트 정보

### GET `/health`
- **기능**: Health

#### Responses
- **200**: Successful Response
  - Content-Type: `application/json`
`Object`

---

### GET `/dashboard/overlay`
- **기능**: Dashboard Overlay

#### Responses
- **200**: Successful Response
  - Content-Type: `application/json`
**[OverlayDashboardResponse](#schema-overlaydashboardresponse)**

---

### POST `/unreal/zones/{zone_id}/focus`
- **기능**: Focus Unreal Zone

#### Parameters
| 파라미터명 | 위치 (In) | 타입 | 필수 여부 | 설명 |
| :--- | :--- | :--- | :--- | :--- |
| `zone_id` | path | `string` | Yes |  |

#### Request Body
- Content-Type: `application/json`
**[UnrealZoneFocusRequest](#schema-unrealzonefocusrequest)**

#### Responses
- **202**: Successful Response
  - Content-Type: `application/json`
**[UnrealZoneFocusResponse](#schema-unrealzonefocusresponse)**
- **422**: Validation Error
  - Content-Type: `application/json`
**[HTTPValidationError](#schema-httpvalidationerror)**

---

### POST `/chat/sessions`
- **기능**: Create Session

#### Request Body
- Content-Type: `application/json`
**[CreateSessionRequest](#schema-createsessionrequest)**

#### Responses
- **201**: Successful Response
  - Content-Type: `application/json`
**[SessionResponse](#schema-sessionresponse)**
- **422**: Validation Error
  - Content-Type: `application/json`
**[HTTPValidationError](#schema-httpvalidationerror)**

---

### GET `/chat/sessions`
- **기능**: List Sessions

#### Parameters
| 파라미터명 | 위치 (In) | 타입 | 필수 여부 | 설명 |
| :--- | :--- | :--- | :--- | :--- |
| `user_id` | query | `string` \| `null` | No |  |
| `unreal_client_id` | query | `string` \| `null` | No |  |
| `limit` | query | `integer` | No |  |

#### Responses
- **200**: Successful Response
  - Content-Type: `application/json`
**[SessionListResponse](#schema-sessionlistresponse)**
- **422**: Validation Error
  - Content-Type: `application/json`
**[HTTPValidationError](#schema-httpvalidationerror)**

---

### GET `/chat/sessions/{session_id}/messages`
- **기능**: List Session Messages

#### Parameters
| 파라미터명 | 위치 (In) | 타입 | 필수 여부 | 설명 |
| :--- | :--- | :--- | :--- | :--- |
| `session_id` | path | `string` | Yes |  |
| `limit` | query | `integer` \| `null` | No |  |
| `max_content_chars` | query | `integer` \| `null` | No |  |

#### Responses
- **200**: Successful Response
  - Content-Type: `application/json`
**[SessionMessagesResponse](#schema-sessionmessagesresponse)**
- **422**: Validation Error
  - Content-Type: `application/json`
**[HTTPValidationError](#schema-httpvalidationerror)**

---

### POST `/chat/messages`
- **기능**: Post Chat Message

#### Parameters
| 파라미터명 | 위치 (In) | 타입 | 필수 여부 | 설명 |
| :--- | :--- | :--- | :--- | :--- |
| `x-correlation-id` | header | `string` \| `null` | No |  |

#### Request Body
- Content-Type: `application/json`
**[ChatRequest](#schema-chatrequest)**

#### Responses
- **200**: Successful Response
  - Content-Type: `application/json`
**[ChatResponse](#schema-chatresponse)**
- **422**: Validation Error
  - Content-Type: `application/json`
**[HTTPValidationError](#schema-httpvalidationerror)**

---

### POST `/events/robot-command`
- **기능**: Receive Robot Event

#### Request Body
- Content-Type: `application/json`
**[CompletionEventRequest](#schema-completioneventrequest)**

#### Responses
- **200**: Successful Response
  - Content-Type: `application/json`
**[ChatResponse](#schema-chatresponse)**
- **422**: Validation Error
  - Content-Type: `application/json`
**[HTTPValidationError](#schema-httpvalidationerror)**

---

## 3. Schemas (데이터 모델)

### <a name="schema-chatmessage"></a>ChatMessage
- **타입**: `object`

| 필드명 | 타입 | 필수 여부 | 설명 |
| :--- | :--- | :--- | :--- |
| `message_id` | `string` | No |  |
| `session_id` | `string` | Yes |  |
| `role` | **[MessageRole](#schema-messagerole)** | Yes |  |
| `content` | `string` | Yes |  |
| `correlation_id` | `string` | Yes |  |
| `created_at` | `string` | No |  |

### <a name="schema-chatrequest"></a>ChatRequest
- **타입**: `object`

| 필드명 | 타입 | 필수 여부 | 설명 |
| :--- | :--- | :--- | :--- |
| `session_id` | `string` \| `null` | No |  |
| `message` | `string` | Yes |  |
| `user_id` | `string` \| `null` | No |  |
| `unreal_client_id` | `string` \| `null` | No |  |
| `idempotency_key` | `string` \| `null` | No |  |

### <a name="schema-chatresponse"></a>ChatResponse
- **타입**: `object`

| 필드명 | 타입 | 필수 여부 | 설명 |
| :--- | :--- | :--- | :--- |
| `session_id` | `string` | Yes |  |
| `correlation_id` | `string` | Yes |  |
| `message` | **[ChatMessage](#schema-chatmessage)** | Yes |  |
| `command_id` | `string` \| `null` | No |  |
| `status` | **[CommandStatus](#schema-commandstatus)** \| `null` | No |  |
| `events` | Array<**[DomainEvent](#schema-domainevent)**> | No |  |

### <a name="schema-commandstatus"></a>CommandStatus
- **타입**: `string`
- **가능한 값 (Enum)**:
  - `pending`
  - `accepted`
  - `running`
  - `completed`
  - `failed`
  - `pending_confirmation`

### <a name="schema-completioneventrequest"></a>CompletionEventRequest
- **타입**: `object`

| 필드명 | 타입 | 필수 여부 | 설명 |
| :--- | :--- | :--- | :--- |
| `event_type` | `string` | Yes |  |
| `correlation_id` | `string` | Yes |  |
| `session_id` | `string` | Yes |  |
| `command_id` | `string` | Yes |  |
| `payload` | `Object` | No |  |

### <a name="schema-createsessionrequest"></a>CreateSessionRequest
- **타입**: `object`

| 필드명 | 타입 | 필수 여부 | 설명 |
| :--- | :--- | :--- | :--- |
| `user_id` | `string` \| `null` | No |  |
| `unreal_client_id` | `string` \| `null` | No |  |

### <a name="schema-domainevent"></a>DomainEvent
- **타입**: `object`

| 필드명 | 타입 | 필수 여부 | 설명 |
| :--- | :--- | :--- | :--- |
| `event_id` | `string` | No |  |
| `event_type` | `string` | Yes |  |
| `correlation_id` | `string` | Yes |  |
| `session_id` | `string` | Yes |  |
| `command_id` | `string` \| `null` | No |  |
| `occurred_at` | `string` | No |  |
| `payload` | `Object` | No |  |

### <a name="schema-httpvalidationerror"></a>HTTPValidationError
- **타입**: `object`

| 필드명 | 타입 | 필수 여부 | 설명 |
| :--- | :--- | :--- | :--- |
| `detail` | Array<**[ValidationError](#schema-validationerror)**> | No |  |

### <a name="schema-messagerole"></a>MessageRole
- **타입**: `string`
- **가능한 값 (Enum)**:
  - `user`
  - `assistant`
  - `system`

### <a name="schema-overlaydashboardresponse"></a>OverlayDashboardResponse
- **타입**: `object`

| 필드명 | 타입 | 필수 여부 | 설명 |
| :--- | :--- | :--- | :--- |
| `greenhouse_id` | `string` | Yes |  |
| `zones` | Array<**[OverlayZone](#schema-overlayzone)**> | Yes |  |
| `metrics` | Array<**[OverlayMetric](#schema-overlaymetric)**> | Yes |  |
| `workloads` | Array<**[OverlayWorkload](#schema-overlayworkload)**> | Yes |  |
| `command_feed` | Array<`string`> | Yes |  |
| `generated_at` | `string` | Yes |  |

### <a name="schema-overlaymetric"></a>OverlayMetric
- **타입**: `object`

| 필드명 | 타입 | 필수 여부 | 설명 |
| :--- | :--- | :--- | :--- |
| `id` | `string` | Yes |  |
| `title` | `string` | Yes |  |
| `subtitle` | `string` | Yes |  |
| `value` | `number` | Yes |  |
| `unit` | `string` | Yes |  |
| `trend_percent` | `number` | Yes |  |
| `series` | Array<`number`> | No |  |

### <a name="schema-overlayworkload"></a>OverlayWorkload
- **타입**: `object`

| 필드명 | 타입 | 필수 여부 | 설명 |
| :--- | :--- | :--- | :--- |
| `id` | `string` | Yes |  |
| `title` | `string` | Yes |  |
| `subtitle` | `string` | Yes |  |
| `value` | `number` | Yes |  |
| `unit` | `string` | Yes |  |
| `status` | `string` | Yes |  |
| `active` | `boolean` | No |  |

### <a name="schema-overlayzone"></a>OverlayZone
- **타입**: `object`

| 필드명 | 타입 | 필수 여부 | 설명 |
| :--- | :--- | :--- | :--- |
| `id` | `string` | Yes |  |
| `name` | `string` | Yes |  |
| `subtitle` | `string` | Yes |  |
| `active` | `boolean` | No |  |

### <a name="schema-sessionlistresponse"></a>SessionListResponse
- **타입**: `object`

| 필드명 | 타입 | 필수 여부 | 설명 |
| :--- | :--- | :--- | :--- |
| `sessions` | Array<**[SessionSummaryResponse](#schema-sessionsummaryresponse)**> | Yes |  |

### <a name="schema-sessionmessagesresponse"></a>SessionMessagesResponse
- **타입**: `object`

| 필드명 | 타입 | 필수 여부 | 설명 |
| :--- | :--- | :--- | :--- |
| `session_id` | `string` | Yes |  |
| `messages` | Array<**[ChatMessage](#schema-chatmessage)**> | Yes |  |

### <a name="schema-sessionresponse"></a>SessionResponse
- **타입**: `object`

| 필드명 | 타입 | 필수 여부 | 설명 |
| :--- | :--- | :--- | :--- |
| `session_id` | `string` | Yes |  |
| `user_id` | `string` \| `null` | Yes |  |
| `unreal_client_id` | `string` \| `null` | Yes |  |
| `created_at` | `string` \| `null` | No |  |

### <a name="schema-sessionsummaryresponse"></a>SessionSummaryResponse
- **타입**: `object`

| 필드명 | 타입 | 필수 여부 | 설명 |
| :--- | :--- | :--- | :--- |
| `session_id` | `string` | Yes |  |
| `user_id` | `string` \| `null` | Yes |  |
| `unreal_client_id` | `string` \| `null` | Yes |  |
| `created_at` | `string` \| `null` | No |  |
| `message_count` | `integer` | No |  |
| `last_message_at` | `string` \| `null` | No |  |
| `last_message_preview` | `string` \| `null` | No |  |
| `first_user_message_preview` | `string` \| `null` | No |  |

### <a name="schema-unrealzonefocusrequest"></a>UnrealZoneFocusRequest
- **타입**: `object`

| 필드명 | 타입 | 필수 여부 | 설명 |
| :--- | :--- | :--- | :--- |
| `unreal_client_id` | `string` | No |  |
| `idempotency_key` | `string` \| `null` | No |  |

### <a name="schema-unrealzonefocusresponse"></a>UnrealZoneFocusResponse
- **타입**: `object`

| 필드명 | 타입 | 필수 여부 | 설명 |
| :--- | :--- | :--- | :--- |
| `status` | `string` | Yes |  |
| `zone_id` | `string` | Yes |  |
| `unreal_client_id` | `string` | Yes |  |
| `command_id` | `string` | Yes |  |
| `api_path` | `string` | Yes |  |
| `issued_at` | `string` | Yes |  |

### <a name="schema-validationerror"></a>ValidationError
- **타입**: `object`

| 필드명 | 타입 | 필수 여부 | 설명 |
| :--- | :--- | :--- | :--- |
| `loc` | Array<`string` \| `integer`> | Yes |  |
| `msg` | `string` | Yes |  |
| `type` | `string` | Yes |  |
