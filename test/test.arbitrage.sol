// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "forge-std/Test.sol";
import "../contracts/Execute.sol";

contract FlashArbitrageTest is Test {
    FlashArbitrage public flashArbitrage;
    address public token0 = address(0x1);
    address public token1 = address(0x2);

    function setUp() public {
        flashArbitrage = new FlashArbitrage();
    }

    function testGetTokenPairs() public {
        address[] memory pairs = flashArbitrage.getTokenPairs();
        assertGt(pairs.length, 0, "Should have token pairs");
    }

    function testGetReserves() public {
        uint112 reserve0;
        uint112 reserve1;
        (reserve0, reserve1) = flashArbitrage.getReserves(token0, token1);
        assertGt(reserve0, 0, "Reserve 0 should be greater than 0");
        assertGt(reserve1, 0, "Reserve 1 should be greater than 0");
    }

    function testExecuteArbitrage() public {
        address[] memory path = new address[](2);
        path[0] = token0;
        path[1] = token1;
        
        bool success = flashArbitrage.executeArbitrage(path, 100 ether);
        assertTrue(success, "Arbitrage execution should succeed");
    }
}
