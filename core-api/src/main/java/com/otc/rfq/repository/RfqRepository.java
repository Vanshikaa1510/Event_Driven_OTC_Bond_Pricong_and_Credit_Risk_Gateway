package com.otc.rfq.repository;

import com.otc.rfq.domain.RfqRecord;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

public interface RfqRepository extends JpaRepository<RfqRecord, UUID> {
    Optional<RfqRecord> findByClientIdAndIdempotencyKey(String clientId, String idempotencyKey);
    List<RfqRecord> findAllByOrderByCreatedAtDesc(Pageable pageable);
}