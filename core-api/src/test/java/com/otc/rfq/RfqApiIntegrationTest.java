package com.otc.rfq;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.hamcrest.Matchers.nullValue;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.otc.rfq.domain.RfqStatus;
import com.otc.rfq.service.RfqService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.dao.DataAccessException;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.springframework.test.web.servlet.MvcResult;

@Testcontainers(disabledWithoutDocker = true)
@SpringBootTest
@AutoConfigureMockMvc
class RfqApiIntegrationTest {
    private static final String API_KEY = "integration-test-key-0123456789abcdef";

    @Container
    private static final PostgreSQLContainer<?> POSTGRES =
            new PostgreSQLContainer<>("pgvector/pgvector:pg16")
                    .withDatabaseName("otc_rfq")
                    .withUsername("otc_demo")
                    .withPassword("integration-password");

    @DynamicPropertySource
    static void configureProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
        registry.add("spring.kafka.listener.auto-startup", () -> false);
        registry.add("rfq.outbox.poll-ms", () -> 3_600_000);
        registry.add("rfq.api.key", () -> API_KEY);
    }

    @Autowired
    private org.springframework.test.web.servlet.MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private RfqService rfqService;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Test
    void persistsSubmissionAndStateTransitionsInAuditHistory() throws Exception {
        MvcResult submission = mockMvc.perform(post("/api/rfqs")
                        .header("X-API-Key", API_KEY)
                        .header("Idempotency-Key", "integration-" + java.util.UUID.randomUUID())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"clientId":"DEMO-001","rawText":"Please quote a $1M buy of Apple 2030 bonds."}
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.status").value("RECEIVED"))
                .andReturn();

        JsonNode response = objectMapper.readTree(submission.getResponse().getContentAsString());
        String rfqId = response.required("id").asText();

        mockMvc.perform(get("/api/rfqs/{id}/history", rfqId).header("X-API-Key", API_KEY))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].eventType").value("SUBMITTED"))
                .andExpect(jsonPath("$[0].previousStatus").value(nullValue()))
                .andExpect(jsonPath("$[0].newStatus").value("RECEIVED"));

        rfqService.applyStatus(java.util.UUID.fromString(rfqId), RfqStatus.PROCESSING);

        mockMvc.perform(get("/api/rfqs/{id}/history", rfqId).header("X-API-Key", API_KEY))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(2))
                .andExpect(jsonPath("$[1].eventType").value("STATUS_CHANGED"))
                .andExpect(jsonPath("$[1].previousStatus").value("RECEIVED"))
                .andExpect(jsonPath("$[1].newStatus").value("PROCESSING"));

        assertThrows(DataAccessException.class, () -> jdbcTemplate.update(
                "UPDATE rfq_audit_events SET new_status = new_status WHERE rfq_id = ?",
                java.util.UUID.fromString(rfqId)));
    }
}
