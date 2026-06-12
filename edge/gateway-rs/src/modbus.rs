//! Async Modbus TCP client.
//!
//! rmodbus is a sans-io frame layer: it builds/parses Modbus ADUs and
//! we own the socket. The same frames work against the bench
//! `modbus-sim` server and a real PLC — only the endpoint changes.

use std::time::Duration;

use anyhow::{Context, Result};
use rmodbus::{client::ModbusRequest, guess_response_frame_len, ModbusProto};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;
use tokio::time::timeout;

pub struct ModbusClient {
    stream: TcpStream,
    unit_id: u8,
    tr_id: u16,
    io_timeout: Duration,
}

impl ModbusClient {
    pub async fn connect(host: &str, port: u16, unit_id: u8, io_timeout: Duration) -> Result<Self> {
        let addr = format!("{host}:{port}");
        let stream = timeout(io_timeout, TcpStream::connect(&addr))
            .await
            .with_context(|| format!("connect timeout to {addr}"))?
            .with_context(|| format!("connect failed to {addr}"))?;
        stream.set_nodelay(true).ok();
        Ok(Self { stream, unit_id, tr_id: 1, io_timeout })
    }

    /// Read `count` holding registers starting at `reg` (function 0x03).
    pub async fn read_holdings(&mut self, reg: u16, count: u16) -> Result<Vec<u16>> {
        let mut mreq = ModbusRequest::new(self.unit_id, ModbusProto::TcpUdp);
        self.tr_id = self.tr_id.wrapping_add(1).max(1);
        mreq.tr_id = self.tr_id;

        let mut request = Vec::new();
        mreq.generate_get_holdings(reg, count, &mut request)
            .context("generate_get_holdings failed")?;

        timeout(self.io_timeout, self.stream.write_all(&request))
            .await
            .context("modbus write timeout")?
            .context("modbus write failed")?;

        // MBAP header first (6 bytes), then the rest of the ADU.
        let mut head = [0u8; 6];
        timeout(self.io_timeout, self.stream.read_exact(&mut head))
            .await
            .context("modbus read timeout (header)")?
            .context("modbus read failed (header)")?;

        let frame_len = guess_response_frame_len(&head, ModbusProto::TcpUdp)
            .context("bad modbus response header")?;
        let mut response = Vec::with_capacity(frame_len as usize);
        response.extend_from_slice(&head);
        if frame_len > 6 {
            let mut rest = vec![0u8; (frame_len - 6) as usize];
            timeout(self.io_timeout, self.stream.read_exact(&mut rest))
                .await
                .context("modbus read timeout (body)")?
                .context("modbus read failed (body)")?;
            response.extend(rest);
        }

        let mut words = Vec::with_capacity(count as usize);
        mreq.parse_u16(&response, &mut words)
            .context("modbus response carries an exception or malformed body")?;
        Ok(words)
    }
}
