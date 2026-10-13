package com.otc.rfq.api;

import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.otc.rfq.service.DashboardService;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(DashboardController.class)
@TestPropertySource(properties = "rfq.api.key=0123456789abcdef0123456789abcdef")
class ApiKeyFilterTest {
    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private DashboardService dashboardService;

    @Test
    void rejectsPlaceholderApiKeyConfiguration() {
        assertThrows(
                IllegalStateException.class,
                () -> new ApiKeyFilter("replace-with-at-least-32-random-characters"));
    }

    @Test
    void rejectsApiRequestsWithoutAKey() throws Exception {
        mockMvc.perform(get("/api/dashboard/clients"))
                .andExpect(status().isUnauthorized())
                .andExpect(content().json("{\"error\":\"Unauthorized\"}"));
    }

    @Test
    void rejectsIncorrectApiKeys() throws Exception {
        mockMvc.perform(get("/api/dashboard/clients").header("X-API-Key", "incorrect-key"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void acceptsConfiguredApiKeyAndCallsController() throws Exception {
        when(dashboardService.listClients()).thenReturn(List.of("DEMO-001"));

        mockMvc.perform(get("/api/dashboard/clients").header("X-API-Key", "0123456789abcdef0123456789abcdef"))
                .andExpect(status().isOk())
                .andExpect(content().json("[\"DEMO-001\"]"));

        verify(dashboardService).listClients();
    }
}
