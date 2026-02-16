; Verification fixture stub for sum_u32_le pipeline wiring checks.
; Expected to FAIL lli_tests unless the task vectors align with this implementation.
define i64 @f(i8* %in_ptr, i32 %in_len, i8* %out_ptr, i32 %out_cap) {
entry:
  ret i64 0
}
