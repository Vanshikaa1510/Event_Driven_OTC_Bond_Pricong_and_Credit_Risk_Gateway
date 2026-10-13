package com.otc.rfq.repository;

import com.otc.rfq.domain.RfqAuditEvent;
import java.util.List;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface RfqAuditRepository extends JpaRepository<RfqAuditEvent, Long> {
    List<RfqAuditEvent> findAllByRfqIdOrderByOccurredAtAscIdAsc(UUID rfqId);
}
