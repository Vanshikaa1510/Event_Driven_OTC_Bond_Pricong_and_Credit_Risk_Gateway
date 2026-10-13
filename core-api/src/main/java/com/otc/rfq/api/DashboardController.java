package com.otc.rfq.api;

import com.otc.rfq.service.DashboardService;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.util.List;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@Validated
@RestController
@RequestMapping("/api/dashboard")
public class DashboardController {
    private final DashboardService dashboardService;

    public DashboardController(DashboardService dashboardService) {
        this.dashboardService = dashboardService;
    }

    @GetMapping("/clients")
    public List<String> clients() {
        return dashboardService.listClients();
    }

    @GetMapping("/summary")
    public DashboardSummary summary(
            @RequestParam @NotBlank @Size(max = 64) String clientId) {
        return dashboardService.getSummary(clientId);
    }
}
